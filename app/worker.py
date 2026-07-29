# app/worker.py - Modifica le funzioni che usano il database
#
# Channel document example:
# {
#   "url": "https://www.youtube.com/@ExampleChannel",
#   "active": true,
#   "include_videos": true,
#   "include_streams": false
# }
# Defaults (when fields are absent): include_videos=True, include_streams=False

import asyncio
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import queue


from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import get_database, close_thread_connection, is_database_connected
from app.config import settings
from app.models import Video
from app.constants import (
    YDL_COMMON_OPTS, YDL_INFO_OPTS, YDL_FLAT_OPTS, YDL_DOWNLOAD_OPTS,
    YDL_BULK_DOWNLOAD_OPTS, RATE_LIMIT_CALLS_PER_MINUTE, DOWNLOAD_ARCHIVE_SUFFIX
)
from app.error_handlers import handle_download_error, handle_extraction_error
from app.logging_config import configure_named_logger
from app.util.youtube.yt_dlp_client import YtDlpClient
from app.util.youtube.url_builder import build_channel_tab_url

logger = configure_named_logger('app_worker')

# Global variables
scheduler = None
scan_in_progress = False
scan_should_stop = False

# Queue for communication between threads
command_queue = queue.Queue()

# Metrics for monitoring
metrics = {
    'channels_scanned': 0,
    'channels_found': 0,
    'videos_downloaded': 0,
    'download_errors': 0,
    'total_download_size': 0,
    'last_run_start': None,
    'last_run_end': None,
    'last_run_duration': 0
}

def sanitize_filename(filename: Optional[str]) -> str:
    """Remove unsafe characters from filename"""
    if filename is None:
        return "unknown_channel"
    
    filename = str(filename)
    unsafe_chars = '<>:"/\\|?*'
    for char in unsafe_chars:
        filename = filename.replace(char, '_')
    
    filename = filename.strip('. ')
    return filename or "unknown_channel"

# Backward-compatible alias kept for any code that still references
# YouTubeDownloader directly.  New code should use YtDlpClient.
YouTubeDownloader = YtDlpClient

# Thread worker function
def worker_thread():
    """Main worker thread function"""
    global scan_in_progress, scan_should_stop, metrics
    
    logger.info(f"Worker thread {threading.get_ident()} started")
    
    try:
        # Initialize downloader in this thread
        cookies_file = settings.COOKIES_FILE if hasattr(settings, 'COOKIES_FILE') else None
        downloader = YtDlpClient(settings.DOWNLOAD_PATH, cookies_file)
        
        while True:
            try:
                # Check for commands (timeout to allow checking stop flag)
                try:
                    cmd = command_queue.get(timeout=1)
                except queue.Empty:
                    # No command, just continue
                    pass
                else:
                    if cmd == 'stop':
                        logger.info("Stop command received")
                        scan_should_stop = True
                    elif cmd == 'start_scan':
                        logger.info("Start scan command received")
                        if not settings.DEBUG_MODE:
                            # Run scan in a separate thread to not block command processing
                            scan_thread = threading.Thread(target=run_scan, args=(downloader,))
                            scan_thread.daemon = True
                            scan_thread.start()
                        else:
                            logger.info("Start scan DEBUG MODE")
                
                # Small sleep to prevent CPU spinning
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in worker thread: {e}")
                time.sleep(1)
    
    finally:
        # Clean up database connection for this thread
        close_thread_connection()
        logger.info(f"Worker thread {threading.get_ident()} stopped")

def run_scan(downloader):
    """Run the actual scan (in a thread)"""
    global scan_in_progress, scan_should_stop, metrics
    
    if scan_in_progress:
        logger.warning("Scan already in progress")
        return
    
    thread_id = threading.get_ident()
    logger.info(f"Scan thread {thread_id} started")
    
    scan_in_progress = True
    scan_should_stop = False
    
    metrics['last_run_start'] = datetime.utcnow()
    logger.info("=" * 50)
    logger.info("🚀 Starting scan of all channels")
    
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Run the async part
            loop.run_until_complete(async_scan(downloader))
        finally:
            # Clean up loop
            loop.close()
        
    except Exception as e:
        logger.error(f"Fatal error in scan: {e}")
    
    finally:
        scan_in_progress = False
        scan_should_stop = False
        metrics['last_run_end'] = datetime.utcnow()
        if metrics['last_run_start']:
            duration = (metrics['last_run_end'] - metrics['last_run_start']).total_seconds()
            metrics['last_run_duration'] = duration
        
        # Close thread's database connection
        close_thread_connection()
        logger.info(f"Scan thread {thread_id} finished")

async def async_scan(downloader):
    """Async part of the scan (database operations)"""
    global scan_should_stop, metrics
    
    # Check database connection first
    #if not is_database_connected():
    #    logger.error("Database not connected, aborting scan")
    #    return
    
    try:
        # Get database connection for this thread
        db = get_database()
        
        # Get active channels
        channels = await db.channels.find(
            {"active": True}
        ).sort("last_scan", 1).to_list(length=100)
        
        if not channels:
            logger.info("No active channels found")
            return
        
        logger.info(f"Found {len(channels)} active channels to scan")
        
        # Reset metrics
        metrics['channels_found']= len(channels)
        metrics['channels_scanned'] = 0
        metrics['videos_downloaded'] = 0
        metrics['download_errors'] = 0
        
        # Scan channels
        for channel in channels:
            if scan_should_stop:
                logger.info("Scan stopped by user request")
                break
            
            try:
                await scan_channel_sync(downloader, channel)
            except Exception as e:
                logger.error(f"Error scanning channel, continuing: {e}")
                continue
        
        # Log summary
        logger.info("=" * 50)
        logger.info(f"📊 Scan completed:")
        logger.info(f"   Channels scanned: {metrics['channels_scanned']}")
        logger.info(f"   Videos downloaded: {metrics['videos_downloaded']}")
        logger.info(f"   Download errors: {metrics['download_errors']}")
        logger.info(f"   Total size: {metrics['total_download_size'] / 1024 / 1024:.1f} MB")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"Error in async_scan: {e}")
        raise

async def scan_channel_sync(downloader, channel):
    """Scan a single channel (runs downloader in thread).

    Reads ``include_videos`` and ``include_streams`` from the channel document.
    ``include_videos`` defaults to ``True`` and ``include_streams`` defaults to
    ``False`` when the fields are absent, preserving backward compatibility.
    For each enabled tab the function:
      1. Bulk-downloads new audio via yt-dlp (archive-based deduplication).
      2. Fetches full metadata for every newly downloaded video.
      3. Upserts the video record in the DB.

    Channel document example::

        {
          "url": "https://www.youtube.com/@ExampleChannel",
          "active": true,
          "include_videos": true,
          "include_streams": false
        }
    """
    global scan_should_stop, metrics

    db = get_database()

    channel_name_raw = channel.get('name') or channel.get('channel_id') or 'Unknown'
    channel_name = sanitize_filename(channel_name_raw)

    logger.info(f"🔍 Scanning channel: {channel_name}")

    # --- Determine which tabs to scan (backward-compatible defaults) ---
    include_videos: bool = channel.get('include_videos', True)
    include_streams: bool = channel.get('include_streams', False)

    tabs_to_scan: List[str] = []
    if include_videos:
        tabs_to_scan.append('videos')
    if include_streams:
        tabs_to_scan.append('streams')

    if not tabs_to_scan:
        logger.warning(
            f"⚠️ Channel '{channel_name}' has both include_videos and include_streams "
            "disabled – skipping yt-dlp calls."
        )
        await db.channels.update_one(
            {"_id": channel['_id']},
            {"$set": {"last_scan": datetime.utcnow()}}
        )
        metrics['channels_scanned'] += 1
        return

    loop = asyncio.get_event_loop()

    # In-memory set for deduplication within this run (across tabs).
    processed_video_ids: set = set()

    # Track whether we have updated channel info yet (prefer videos tab).
    channel_info_updated = False

    for tab in tabs_to_scan:
        if scan_should_stop:
            logger.info(f"Scan stopped during channel {channel_name}")
            return

        source_url = build_channel_tab_url(channel['url'], tab)
        logger.info(f"📡 Scanning tab '{tab}' for {channel_name}: {source_url}")

        # --- Fetch channel metadata (once, from first available tab) ---
        if not channel_info_updated:
            channel_info, _ = await loop.run_in_executor(
                None,
                downloader.get_channel_entries,
                source_url,
                10,
            )

            if scan_should_stop:
                logger.info(f"Scan stopped during channel {channel_name}")
                return

            if channel_info:
                await update_channel_info_db(db, channel, channel_info)
                channel_info_updated = True
            else:
                logger.warning(f"No channel info returned for {channel_name} (tab: {tab})")

        # --- Bulk download new content for this tab ---
        logger.info(f"📥 Starting bulk download for {channel_name} [{tab}]…")

        downloaded_videos = await loop.run_in_executor(
            None,
            downloader.bulk_download_channel_tab,
            source_url,
            channel_name,
            10,  # Max 10 videos per tab per scan
        )

        if not downloaded_videos:
            logger.info(f"No new videos downloaded for {channel_name} [{tab}]")
        else:
            logger.info(
                f"Downloaded {len(downloaded_videos)} new videos for {channel_name} [{tab}]"
            )

            for video_result in downloaded_videos:
                try:
                    video_id = video_result['video_id']

                    # Skip if already processed in this run (other tab)
                    if video_id in processed_video_ids:
                        logger.debug(f"⏭️ Dedup skip (already processed this run): {video_id}")
                        continue
                    processed_video_ids.add(video_id)

                    # Get full metadata for the downloaded video
                    full_metadata = await loop.run_in_executor(
                        None,
                        downloader.get_video_metadata,
                        video_id,
                    )

                    # Create video info dict for database
                    video_info = {
                        'id': video_id,
                        'title': video_result['title'],
                        'duration': full_metadata.get('duration') if full_metadata else None,
                        'upload_date': full_metadata.get('upload_date') if full_metadata else None,
                        'timestamp': full_metadata.get('timestamp') if full_metadata else None,
                        'view_count': full_metadata.get('view_count') if full_metadata else None,
                        'channel': channel_name,
                        'channel_id': channel.get('channel_id'),
                    }

                    # Save to database
                    await save_video_metadata_db(
                        db,
                        video_info=video_info,
                        channel=channel,
                        downloaded=True,
                        file_path=video_result['file_path'],
                        file_size=video_result['file_size'],
                        full_metadata=full_metadata or video_result['metadata'],
                    )

                    metrics['videos_downloaded'] += 1
                    metrics['total_download_size'] += video_result['file_size']

                    logger.info(
                        f"✅ Processed: {video_result['title']} "
                        f"({video_result['file_size'] / 1024 / 1024:.1f} MB)"
                    )

                except Exception as e:
                    logger.error(
                        f"Error processing downloaded video {video_result.get('video_id')}: {e}"
                    )
                    metrics['download_errors'] += 1

    # Update last scan timestamp
    await db.channels.update_one(
        {"_id": channel['_id']},
        {"$set": {"last_scan": datetime.utcnow()}}
    )

    metrics['channels_scanned'] += 1

async def update_channel_info_db(db, db_channel: Dict, yt_channel_info: Dict):
    """Update channel info in database"""
    updates = {}
    
    if yt_channel_info.get('name'):
        updates['name'] = yt_channel_info['name']
    
    if yt_channel_info.get('id'):
        updates['channel_id'] = yt_channel_info['id']
    
    if yt_channel_info.get('description'):
        updates['description'] = yt_channel_info['description']
    
    if yt_channel_info.get('thumbnails'):
        updates['thumbnails'] = yt_channel_info['thumbnails']
        if yt_channel_info['thumbnails']:
            updates['thumbnail_url'] = yt_channel_info['thumbnails'][-1]['url']
    
    if yt_channel_info.get('subscriber_count'):
        updates['subscriber_count'] = yt_channel_info['subscriber_count']
    
    if yt_channel_info.get('video_count'):
        updates['video_count'] = yt_channel_info['video_count']
    
    if updates:
        await db.channels.update_one(
            {"_id": db_channel['_id']},
            {"$set": updates}
        )

async def filter_new_videos_db(db, videos: List[Dict], channel_id: str) -> List[Dict]:
    """
    DEPRECATED: No longer used with bulk download approach.
    yt-dlp now handles duplicate detection automatically.
    """
    return []

async def save_video_metadata_db(
    db,
    video_info: Dict,
    channel: Dict,
    downloaded: bool = False,
    file_path: Optional[str] = None,
    file_size: Optional[int] = None,
    full_metadata: Optional[Dict] = None
):
    """Save video metadata to database"""
    # Prepare upload timestamp
    upload_timestamp = video_info.get('timestamp')
    if upload_timestamp is None and 'upload_date' in video_info and video_info['upload_date']:
        try:
            date_str = str(video_info['upload_date'])
            dt = datetime.strptime(date_str, '%Y%m%d')
            upload_timestamp = dt.timestamp()
        except (ValueError, TypeError):
            upload_timestamp = datetime.utcnow().timestamp()
    elif upload_timestamp is None:
        upload_timestamp = datetime.utcnow().timestamp()

    metadata = full_metadata or video_info
    
    # Extract title
    title = (
        metadata.get('_original_title') or
        metadata.get('original_title') or
        video_info.get('title') or
        metadata.get('title') or
        'Unknown'
    )
    
    # Extract audio format info
    audio_bitrate = None
    audio_codec = None
    
    if 'formats' in metadata and isinstance(metadata['formats'], list):
        audio_formats = [f for f in metadata['formats'] if f.get('vcodec') == 'none']
        if audio_formats:
            best_audio = audio_formats[-1]
            if best_audio.get('abr'):
                try:
                    audio_bitrate = float(best_audio['abr'])
                except (TypeError, ValueError):
                    audio_bitrate = None
            audio_codec = best_audio.get('acodec')
    
    # Ensure duration is int
    duration = video_info.get('duration', 0)
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0
    
    # Build Video object
    video = Video(
        video_id=video_info.get('id', 'unknown'),
        channel_id=channel.get('channel_id', 'unknown'),
        channel_name=channel.get('name', channel.get('channel_id', 'Unknown')),
        channel_url=channel.get('url'),
        title=title,
        description=video_info.get('description'),
        duration=duration,
        upload_timestamp=upload_timestamp,
        download_date=datetime.utcnow() if downloaded else None,
        file_path=file_path,
        file_size=file_size,
        downloaded=downloaded,
        thumbnails=metadata.get('thumbnails'),
        thumbnail_url=metadata.get('thumbnail'),
        uploader=metadata.get('uploader'),
        uploader_id=metadata.get('uploader_id'),
        uploader_url=metadata.get('uploader_url'),
        view_count=metadata.get('view_count'),
        like_count=metadata.get('like_count'),
        comment_count=metadata.get('comment_count'),
        availability=metadata.get('availability'),
        is_live=metadata.get('is_live'),
        was_live=metadata.get('was_live'),
        chapters=metadata.get('chapters'),
        format_id=metadata.get('format_id'),
        format_note=metadata.get('format_note'),
        audio_bitrate=audio_bitrate,
        audio_codec=audio_codec,
        filesize_approx=metadata.get('filesize_approx'),
        age_limit=metadata.get('age_limit'),
        categories=metadata.get('categories'),
        tags=metadata.get('tags'),
        raw_info=metadata
    )
    
    # Insert or update in database
    await db.videos.update_one(
        {"video_id": video.video_id, "channel_id": video.channel_id},
        {"$set": video.model_dump(by_alias=True, exclude={"id"})},
        upsert=True
    )

# Public API
def start_worker():
    """Start the background worker thread"""
    global worker_thread_instance
    
    worker_thread_instance = threading.Thread(target=worker_thread, daemon=True)
    worker_thread_instance.start()
    logger.info("✅ Worker thread started")
    
    # Start scheduler
    start_scheduler()

def start_scheduler():
    """Start the background scheduler"""
    global scheduler
    
    if scheduler and scheduler.running:
        return scheduler
    
    scheduler = BackgroundScheduler()
    
    def scheduled_scan():
        """Scheduled scan trigger"""
        logger.info("Scheduled scan triggered")
        command_queue.put('start_scan')
    
    scheduler.add_job(
        func=scheduled_scan,
        trigger=IntervalTrigger(hours=settings.SCAN_INTERVAL_HOURS),
        id='youtube_downloader',
        name=f'Scan YouTube channels every {settings.SCAN_INTERVAL_HOURS} hours',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info(f"✅ Scheduler started - will scan every {settings.SCAN_INTERVAL_HOURS} hours")
    
    # Run initial scan
    command_queue.put('start_scan')
    
    return scheduler

def shutdown_worker():
    """Shutdown the worker"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
    command_queue.put('stop')
    
    # Give threads time to clean up
    time.sleep(2)
    
    # Final cleanup of main thread's connection
    close_thread_connection()
    logger.info("🛑 Worker shutdown")

# Control functions
async def stop_scan():
    """Stop the current scan"""
    command_queue.put('stop')
    return {"status": "stopping"}

def is_scanning():
    """Check if a scan is in progress"""
    return scan_in_progress

def get_metrics():
    """Get current worker metrics"""
    return metrics

async def manual_scan():
    """Manually trigger a scan"""
    logger.info("Manual scan triggered")
    command_queue.put('start_scan')
    return {"status": "success", "message": "Scan started"}