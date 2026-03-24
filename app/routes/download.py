# app/routes/download.py
import logging
import unicodedata
import re
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse, Response
from pathlib import Path
import os
from typing import Optional

from app.auth import require_token
from app.database import get_database
from app.config import settings

logger = logging.getLogger('voiceonly')

router = APIRouter(dependencies=[Depends(require_token)])


def sanitize_download_filename(filename: str, max_length: int = 200) -> str:
    """
    Sanitize filename for safe download
    
    - Removes Unicode non-ASCII characters
    - Prevents directory traversal attacks
    - Limits length
    - Replaces dangerous characters
    
    Args:
        filename: Original filename from video title
        max_length: Maximum filename length
    
    Returns:
        Safe filename for HTTP Content-Disposition
    """
    # Normalize Unicode to ASCII-compatible form
    filename = unicodedata.normalize('NFKD', filename)
    filename = filename.encode('ascii', 'ignore').decode('ascii').strip()
    
    # Remove path separators and control characters
    filename = re.sub(r'[^\w\s.-]', '', filename)
    
    # Replace multiple spaces/dashes with single dash
    filename = re.sub(r'[-\s]+', '-', filename).strip('-')
    
    # Limit length (reserve space for extension)
    if len(filename) > max_length:
        # Try to preserve some context by cutting at word boundary
        words = filename.split('-')
        filename = '-'.join(words[:max_length // 20])  # Simple heuristic
        if not filename:
            filename = "audio"
    
    # Ensure not empty
    filename = filename or "audio"
    
    # Add extension if not present
    if not filename.endswith('.opus'):
        filename = f"{filename}.opus"
    
    return filename

async def get_video_file(video_id: str):
    """
    Find video file by ID
    Returns (file_path, video_info) or (None, None)
    """
    db = get_database()
    
    # Find video in database
    video = await db.videos.find_one({
        "video_id": video_id,
        "downloaded": True
    })
    
    if not video:
        return None, None
    
    file_path = video.get('file_path')
    if not file_path or not Path(file_path).exists():
        return None, None
    
    return Path(file_path), video

@router.get("/{video_id}")
async def download_audio(
    request: Request,
    video_id: str,
    force_download: bool = False
):
    """
    Download audio file for a video
    Supports range requests for resumable downloads
    """
    file_path, video_info = await get_video_file(video_id)
    
    if not file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    filename = sanitize_download_filename(video_info.get('title', video_id))
    
    if force_download:
        # Force download with Content-Disposition: attachment
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type='application/octet-stream',
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    else:
        # Stream for podcast players (supports range requests)
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type='audio/opus'
        )

@router.head("/{video_id}")
async def download_audio_head(video_id: str):
    """
    HEAD request for checking file existence and size
    Used by podcast players
    """
    file_path, video_info = await get_video_file(video_id)
    
    if not file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    file_size = file_path.stat().st_size
    
    return Response(
        status_code=200,
        headers={
            "Content-Length": str(file_size),
            "Content-Type": "audio/opus",
            "Accept-Ranges": "bytes"
        }
    )

@router.get("/{video_id}/info")
async def get_audio_info(video_id: str):
    """
    Get information about the audio file
    """
    db = get_database()
    
    video = await db.videos.find_one({
        "video_id": video_id,
        "downloaded": True
    })
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    file_path = video.get('file_path')
    file_exists = file_path and Path(file_path).exists()
    file_size = Path(file_path).stat().st_size if file_exists else 0
    
    return {
        "video_id": video_id,
        "title": video.get('title'),
        "channel_name": video.get('channel_name'),
        "duration": video.get('duration'),
        "file_exists": file_exists,
        "file_size": file_size,
        "upload_date": video.get('upload_date'),
        "download_url": f"/download/{video_id}"
    }