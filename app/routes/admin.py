# app/routes/admin.py
import asyncio
import logging

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
import re
import os
from bson import ObjectId
from typing import Optional
import yt_dlp 

from app.auth import require_auth
from app.models import Channel, ChannelCreate
from app.database import get_database, is_database_connected
from app.templates import templates
from app.config import settings
from app.constants import YDL_ADMIN_OPTS

from app.worker import manual_scan, stop_scan, is_scanning, get_metrics

# Setup logger
logger = logging.getLogger('youtube-admin')

router = APIRouter(dependencies=[Depends(require_auth)])

def extract_channel_info_with_library(url: str):
    """
    Extract channel info from YouTube URL using yt-dlp library
    instead of shell commands
    """
    try:
        ydl_opts = {**YDL_ADMIN_OPTS, 'cookiefile': settings.COOKIES_FILE if hasattr(settings, 'COOKIES_FILE') else None}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info without downloading
            info = ydl.extract_info(url, download=False)
            
            if info is None:
                return {"name": None, "channel_id": None}
            
            # Extract channel information
            channel_info = {
                "name": info.get('channel', info.get('uploader', info.get('channel_friendly'))),
                "channel_id": info.get('channel_id', info.get('uploader_id')),
                "description": info.get('description'),
                "thumbnail": info.get('thumbnail'),
            }
            
            # Se è una playlist o canale, potremmo avere entries
            if 'entries' in info and len(info['entries']) > 0:
                first_video = info['entries'][0]
                if first_video:
                    channel_info["name"] = channel_info["name"] or first_video.get('channel')
                    channel_info["channel_id"] = channel_info["channel_id"] or first_video.get('channel_id')
            
            return channel_info
            
    except Exception as e:
        logger.error(f"Error extracting channel info with library: {e}")
        # Fallback a regex se la libreria fallisce
        return extract_channel_info_fallback(url)

def extract_channel_info_fallback(url: str):
    """
    Fallback method using regex if library fails
    """
    logger.debug(f"Falling back to regex extraction for {url}")
    
    # Pattern for @username (new format)
    at_match = re.search(r'youtube\.com/@([^/?]+)', url)
    if at_match:
        username = at_match.group(1)
        return {"name": username, "channel_id": f"@{username}"}
    
    # Pattern for /c/ (custom URL)
    c_match = re.search(r'youtube\.com/c/([^/?]+)', url)
    if c_match:
        custom_name = c_match.group(1)
        return {"name": custom_name, "channel_id": f"c/{custom_name}"}
    
    # Pattern for /channel/UC... (actual channel ID)
    channel_match = re.search(r'youtube\.com/channel/(UC[^/?]+)', url)
    if channel_match:
        channel_id = channel_match.group(1)
        return {"name": channel_id, "channel_id": channel_id}
    
    # Pattern for /user/ (old username format)
    user_match = re.search(r'youtube\.com/user/([^/?]+)', url)
    if user_match:
        username = user_match.group(1)
        return {"name": username, "channel_id": f"user/{username}"}
    
    return {"name": None, "channel_id": None}

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Admin dashboard home page"""
    # Check database connection first
    if not is_database_connected():
        return templates.TemplateResponse(
            name="admin/error.html",
            request=request,
            context={
                "request": request,
                "error": "Database non connesso. Verifica che MongoDB sia in esecuzione."
            }
        )
    
    db = get_database()
    
    # Get all channels with video count using aggregation (avoids N+1 queries)
    channel_pipeline = [
        {
            "$lookup": {
                "from": "videos",
                "let": {"channel_id": "$channel_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$channel_id", "$$channel_id"]},
                            "downloaded": True
                        }
                    },
                    {"$count": "count"}
                ],
                "as": "video_stats"
            }
        },
        {
            "$addFields": {
                "video_count": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$video_stats.count", 0]},
                        0
                    ]
                }
            }
        },
        {"$project": {"video_stats": 0}}
    ]
    
    channels = []
    async for channel in db.channels.aggregate(channel_pipeline):
        channels.append({
            "id": str(channel["_id"]),
            "url": channel["url"],
            "name": channel.get("name", "Sconosciuto"),
            "active": channel.get("active", True),
            "last_scan": channel.get("last_scan"),
            "video_count": channel.get("video_count", 0),
            "friendly_name": channel.get("friendly_name")
        })
    
    # Get recent videos
    recent_videos_cursor = db.videos.find(
        {"downloaded": True}
    ).sort("download_date", -1).limit(10)
    
    recent_videos = []
    async for video in recent_videos_cursor:
        upload_date = None
        if video.get("upload_timestamp") is not None:
            try:
                upload_date = datetime.fromtimestamp(float(video["upload_timestamp"]))
            except (TypeError, ValueError, OSError):
                upload_date = None

        recent_videos.append({
            "title": video.get("title", "Unknown"),
            "channel_name": video.get("channel_name", "Unknown"),
            "duration": video.get("duration", 0),
            "upload_date": upload_date,
            "file_size": video.get("file_size", 0)
        })
    
    # Calculate stats using efficient queries
    total_videos = await db.videos.count_documents({"downloaded": True})
    active_channels = await db.channels.count_documents({"active": True})
    
    # Calculate total size using aggregation (much faster than iterating)
    size_pipeline = [
        {"$match": {"downloaded": True, "file_size": {"$exists": True}}},
        {
            "$group": {
                "_id": None,
                "total_size": {"$sum": "$file_size"}
            }
        }
    ]
    
    total_size = 0
    async for result in db.videos.aggregate(size_pipeline):
        total_size = result.get("total_size", 0)
    
    # Find last scan time
    last_scan_channel = await db.channels.find_one(
        {"last_scan": {"$exists": True}},
        sort=[("last_scan", -1)]
    )
    
    last_scan_hours = "N/A"
    if last_scan_channel is not None and last_scan_channel.get("last_scan") is not None:
        hours_ago = (datetime.utcnow() - last_scan_channel["last_scan"]).total_seconds() / 3600
        last_scan_hours = f"{int(hours_ago)}"
    
    stats = {
        "active_channels": active_channels,
        "total_videos": total_videos,
        "total_size_gb": round(total_size / (1024**3), 2) if total_size > 0 else 0,
        "last_scan_hours": last_scan_hours
    }
    
    return templates.TemplateResponse(
        name="admin/dashboard.html",
        request=request,
        context={
            "request": request,
            "channels": channels,
            "recent_videos": recent_videos,
            "stats": stats
        }
    )

@router.get("/channels/add", response_class=HTMLResponse)
async def add_channel_form(request: Request):
    """Show form to add a new channel"""
    return templates.TemplateResponse(
        name="admin/add_channel.html",
        request=request,
        context={}
    )

@router.post("/channels/add")
async def add_channel_submit(
    request: Request,
    url: str = Form(...),
    friendly_name: Optional[str] = Form(None)
):
    """Process the add channel form with optional friendly name"""
    db = get_database()
    
    # Validate URL
    try:
        channel_create = ChannelCreate(url=url)
    except ValueError as e:
        return templates.TemplateResponse(
            name="admin/add_channel.html",
            request=request,
            context={
                "request": request,
                "error": f"URL non valido: {str(e)}",
                "url": url,
                "friendly_name": friendly_name
            }
        )
    
    # Check if channel already exists
    existing = await db.channels.find_one({"url": url})
    if existing is not None:
        return templates.TemplateResponse(
            name="admin/add_channel.html",
            request=request,
            context={
                "request": request,
                "error": "Questo canale è già stato aggiunto!",
                "url": url,
                "friendly_name": friendly_name
            }
        )
    
    # Check if friendly name is already taken
    if friendly_name:
        existing = await db.channels.find_one({"friendly_name": friendly_name})
        if existing is not None:
            return templates.TemplateResponse(
                name="admin/add_channel.html",
                request=request,
                context={
                    "request": request,
                    "error": "Questo friendly name è già utilizzato da un altro canale!",
                    "url": url,
                    "friendly_name": friendly_name
                }
            )
    
    # Extract channel info using the library
    logger.info(f"Extracting channel info for {url}...")
    channel_info = extract_channel_info_with_library(url)
    logger.debug(f"Extracted channel info: {channel_info}")
    
    # Generate friendly name if not provided
    if not friendly_name:
        # Create from channel name: lowercase, replace spaces with hyphens, remove special chars
        base_name = channel_info.get('name', 'channel')
        friendly_name = re.sub(r'[^a-zA-Z0-9]+', '-', base_name.lower()).strip('-')
        
        # Ensure it's not too long and not empty
        friendly_name = friendly_name[:30] or 'channel'
        
        # Make it unique if needed
        base_friendly = friendly_name
        counter = 1
        while True:
            existing = await db.channels.find_one({"friendly_name": friendly_name})
            if not existing:
                break
            friendly_name = f"{base_friendly}-{counter}"
            counter += 1
    
    # Create new channel
    channel = Channel(
        url=url,
        name=channel_info.get("name"),
        friendly_name=friendly_name,
        channel_id=channel_info.get("channel_id"),
        active=True,
        created_at=datetime.utcnow()
    )
    
    # Convert to dict for MongoDB
    channel_dict = channel.model_dump(by_alias=True, exclude={"id"})
    logger.debug(f"Saving channel: {channel_dict}")
    
    # Insert into database
    await db.channels.insert_one(channel_dict)
    
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/channels/{channel_id}/edit", response_class=HTMLResponse)
async def edit_channel_form(request: Request, channel_id: str):
    """Show form to edit channel"""
    db = get_database()
    
    if not ObjectId.is_valid(channel_id):
        raise HTTPException(status_code=400, detail="Invalid channel ID")
    
    channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    return templates.TemplateResponse(
        name="admin/edit_channel.html",
        request=request,
        context={
            "request": request,
            "channel": channel
        }
    )

@router.post("/channels/{channel_id}/edit")
async def edit_channel_submit(
    request: Request,
    channel_id: str,
    friendly_name: str = Form(...),
    active: Optional[str] = Form(None)
):
    """Process edit channel form"""
    db = get_database()
    
    if not ObjectId.is_valid(channel_id):
        raise HTTPException(status_code=400, detail="Invalid channel ID")
    
    # Validate friendly name
    try:
        # Simple validation
        if not re.match(r'^[a-zA-Z0-9_-]+$', friendly_name):
            raise ValueError('Il friendly name può contenere solo lettere, numeri, trattini e underscore')
        if len(friendly_name) > 50:
            raise ValueError('Friendly name troppo lungo (max 50 caratteri)')
    except ValueError as e:
        channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
        return templates.TemplateResponse(
            name="admin/edit_channel.html",
            request=request,
            context={
                "request": request,
                "channel": channel,
                "error": str(e),
                "friendly_name": friendly_name
            }
        )
    
    # Check if friendly name is already taken by another channel
    existing = await db.channels.find_one({
        "friendly_name": friendly_name,
        "_id": {"$ne": ObjectId(channel_id)}
    })
    if existing:
        channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
        return templates.TemplateResponse(
            name="admin/edit_channel.html",
            request=request,
            context={
                "request": request,
                "channel": channel,
                "error": "Questo friendly name è già utilizzato da un altro canale",
                "friendly_name": friendly_name
            }
        )
    
    # Update channel
    update_fields = {"friendly_name": friendly_name}
    if active is not None:
        update_fields["active"] = True if active == "on" else False

    await db.channels.update_one(
        {"_id": ObjectId(channel_id)},
        {"$set": update_fields}
    )
    
    return RedirectResponse(url=f"/admin/channels/{channel_id}", status_code=303)

@router.get("/channels/{channel_id}/toggle")
async def toggle_channel(channel_id: str):
    """Enable/disable a channel"""
    db = get_database()
    
    if not ObjectId.is_valid(channel_id):
        raise HTTPException(status_code=400, detail="Invalid channel ID")
    
    channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Toggle active status
    new_status = not channel.get("active", True)
    await db.channels.update_one(
        {"_id": ObjectId(channel_id)},
        {"$set": {"active": new_status}}
    )
    
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/channels/{channel_id}/delete")
async def delete_channel(channel_id: str):
    """Remove a channel (but keep downloaded videos)"""
    db = get_database()
    
    if not ObjectId.is_valid(channel_id):
        raise HTTPException(status_code=400, detail="Invalid channel ID")
    
    # Delete the channel
    result = await db.channels.delete_one({"_id": ObjectId(channel_id)})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/logs", response_class=HTMLResponse)
async def view_logs(request: Request, clear: Optional[bool] = False):
    """View system logs"""
    log_file = "app.log"
    logs = []
    
    if clear:
        # Clear log file
        open(log_file, 'w').close()
        return RedirectResponse(url="/admin/logs", status_code=303)
    
    # Read last 100 lines from log file
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            logs = f.readlines()[-100:]
    
    return templates.TemplateResponse(
        name="admin/logs.html",
        request=request,
        context={"request": request, "logs": logs}
    )

@router.get("/scan-now")
async def trigger_scan(request: Request):
    """Manually trigger a scan"""
    try:
        result = await manual_scan()
        return templates.TemplateResponse(
            name="admin/scan_started.html",
            request=request,
            context={"request": request, "message": result["message"]}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting scan: {e}")

@router.post("/scan-stop")
async def stop_scan_route():
    """Stop the current scan"""
    result = await stop_scan()
    return result

@router.get("/scan-status")
async def scan_status():
    """Get current scan status"""
    return {
        "scanning": is_scanning(),
        "metrics": get_metrics()
    }

@router.get("/channels/{channel_id}")
async def channel_detail(request: Request, channel_id: str):
    """Show channel details and downloaded videos"""
    db = get_database()
    
    if not ObjectId.is_valid(channel_id):
        raise HTTPException(status_code=400, detail="Invalid channel ID")
    
    channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Get downloaded videos for this channel
    videos_cursor = db.videos.find({
        "channel_id": channel.get('channel_id'),
        "downloaded": True
    }).sort("upload_date", -1).limit(100)
    
    videos = await videos_cursor.to_list(length=100)
    
    return templates.TemplateResponse(
        name="admin/channel_detail.html",
        request=request,
        context={
            "request": request,
            "channel": channel,
            "videos": videos
        }
    )

    # In app/routes/admin.py, aggiungi una route per testare la ricerca canali

@router.get("/channels/lookup/{identifier}")
async def lookup_channel(identifier: str):
    """
    Debug endpoint to see how channel lookup works
    """
    db = get_database()
    
    results = {
        "identifier": identifier,
        "lookups": {}
    }
    
    # Try as MongoDB ObjectId
    if ObjectId.is_valid(identifier):
        channel = await db.channels.find_one({"_id": ObjectId(identifier)})
        results["lookups"]["mongo_id"] = {
            "found": channel is not None,
            "channel": str(channel['_id']) if channel else None
        }
    
    # Try as YouTube channel ID
    channel = await db.channels.find_one({"channel_id": identifier})
    results["lookups"]["youtube_id"] = {
        "found": channel is not None,
        "channel": str(channel['_id']) if channel else None
    }
    
    # Try as name
    channel = await db.channels.find_one({
        "name": {"$regex": f"^{identifier}$", "$options": "i"}
    })
    results["lookups"]["name"] = {
        "found": channel is not None,
        "channel": str(channel['_id']) if channel else None
    }
    
    return results