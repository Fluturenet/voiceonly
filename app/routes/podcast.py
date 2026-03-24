# app/routes/podcast.py
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional

from app.auth import require_token
from app.database import get_database
from app.utils.rss import generate_podcast_feed
from app.constants import FEED_CACHE_MAX_SIZE, FEED_CACHE_DURATION_HOURS

logger = logging.getLogger('voiceonly')

router = APIRouter(dependencies=[Depends(require_token)])


class LRUFeedCache:
    """
    LRU (Least Recently Used) cache for podcast feeds with TTL (Time To Live)
    Prevents unbounded memory growth when caching feed XML
    """
    def __init__(self, max_size: int = FEED_CACHE_MAX_SIZE, ttl_hours: int = FEED_CACHE_DURATION_HOURS):
        self.max_size = max_size
        self.ttl = timedelta(hours=ttl_hours)
        self.cache = {}  # {key: (content, timestamp)}
        self.access_order = []  # Track access order for LRU

    def get(self, key: str) -> Optional[str]:
        """Get cached feed if exists and not expired"""
        if key not in self.cache:
            return None
        
        content, timestamp = self.cache[key]
        if datetime.utcnow() - timestamp > self.ttl:
            # Cached entry expired
            del self.cache[key]
            if key in self.access_order:
                self.access_order.remove(key)
            return None
        
        # Update access order for LRU
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
        
        return content

    def set(self, key: str, content: str):
        """Cache feed XML"""
        # If at capacity, remove least recently used
        if len(self.cache) >= self.max_size and key not in self.cache:
            if self.access_order:
                lru_key = self.access_order.pop(0)
                del self.cache[lru_key]
        
        # Add or update entry
        self.cache[key] = (content, datetime.utcnow())
        
        # Update access order
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
        
        logger.debug(f"Feed cache: stored {key} ({len(self.cache)}/{self.max_size})")

    def clear(self):
        """Clear all cache"""
        self.cache.clear()
        self.access_order.clear()
        logger.debug("Feed cache cleared")


# Initialize global cache
feed_cache = LRUFeedCache()

@router.get("/{identifier}.xml")
async def get_podcast_feed(
    request: Request,
    identifier: str,
    limit: Optional[int] = 50
):
    """
    Generate iTunes-compatible podcast RSS feed for a channel
    
    identifier can be:
    - Friendly name (user-defined short name)
    - MongoDB ObjectId
    - YouTube channel ID (UC... or @username)
    """
    db = get_database()
    
    # Check cache first
    cache_key = f"{identifier}_{limit}"
    cached_feed = feed_cache.get(cache_key)
    if cached_feed:
        return Response(
            content=cached_feed,
            media_type="application/rss+xml; charset=utf-8",
            headers={
                "Cache-Control": f"max-age={int(FEED_CACHE_DURATION_HOURS * 3600)}",
                "X-Cache": "HIT"
            }
        )
    
    # Find channel - try different lookup methods
    channel = None
    
    # Method 1: Try as friendly name
    channel = await db.channels.find_one({"friendly_name": identifier})
    
    # Method 2: Try as MongoDB ObjectId
    if not channel and ObjectId.is_valid(identifier):
        channel = await db.channels.find_one({"_id": ObjectId(identifier)})
    
    # Method 3: Try as YouTube channel ID
    if not channel:
        channel = await db.channels.find_one({"channel_id": identifier})
    
    # Method 4: Try as channel name (case insensitive)
    if not channel:
        channel = await db.channels.find_one({
            "name": {"$regex": f"^{identifier}$", "$options": "i"}
        })
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
        
    # Get downloaded videos for this channel
    videos_cursor = db.videos.find({
        "channel_id": channel.get('channel_id'),
        "downloaded": True
    }).sort("upload_date", -1).limit(limit)
    
    videos = await videos_cursor.to_list(length=limit)
    
    if not videos:
        # Return empty feed if no videos
        videos = []
    
    # Prepare channel info for RSS
    channel_info = {
        'name': channel.get('name', 'Unknown Channel'),
        'url': channel.get('url', ''),
        'description': channel.get('description', ''),
        'thumbnail': channel.get('thumbnail_url'),
        'category': 'Music',
        'explicit': 'No',
        'owner_name': channel.get('name'),
        'owner_email': None,
    }
    
    # Prepare episodes
    episodes = []
    for video in videos:
        upload_timestamp = video.get('upload_timestamp')
        if upload_timestamp is None:
            upload_timestamp = datetime.utcnow().timestamp()

        episodes.append({
            'video_id': video.get('video_id'),
            'title': video.get('title', 'Untitled'),
            'description': video.get('description', ''),
            'upload_timestamp': upload_timestamp,
            'duration': video.get('duration', 0),
            'file_path': video.get('file_path'),
            'file_size': video.get('file_size', 0),
            'thumbnail_url': video.get('thumbnail_url'),
            'explicit': 'No'
        })
    
    # Generate feed
    base_url = str(request.base_url).rstrip('/')
    feed_xml = generate_podcast_feed(channel_info, episodes, base_url)
    
    # Cache the feed
    feed_cache.set(cache_key, feed_xml)
    
    # Return as XML
    return Response(
        content=feed_xml,
        media_type="application/rss+xml; charset=utf-8",
        headers={
            "Cache-Control": f"max-age={int(FEED_CACHE_DURATION_HOURS * 3600)}",
            "X-Cache": "MISS"
        }
    )

@router.get("/{channel_id}/info")
async def get_channel_podcast_info(channel_id: str):
    """
    Get podcast metadata for a channel (useful for debugging)
    """
    db = get_database()
    
    # Find channel - try different lookup methods
    channel = None
    
    if ObjectId.is_valid(channel_id):
        channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
    
    if not channel:
        channel = await db.channels.find_one({"channel_id": channel_id})
    
    if not channel:
        channel = await db.channels.find_one({
            "name": {"$regex": f"^{channel_id}$", "$options": "i"}
        })
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    video_count = await db.videos.count_documents({
        "channel_id": channel.get('channel_id'),
        "downloaded": True
    })
    
    latest_video = await db.videos.find_one({
        "channel_id": channel.get('channel_id'),
        "downloaded": True
    }, sort=[("upload_date", -1)])
    
    # Determine feed URL based on what was used
    if ObjectId.is_valid(channel_id):
        feed_url = f"/podcast/{channel['_id']}.xml"
    else:
        feed_url = f"/podcast/{channel.get('channel_id')}.xml"
    
    return {
        "channel_id": str(channel['_id']),
        "youtube_channel_id": channel.get('channel_id'),
        "name": channel.get('name'),
        "video_count": video_count,
        "latest_video": latest_video.get('title') if latest_video else None,
        "feed_url": feed_url,
        "mongo_id": str(channel['_id'])
    }