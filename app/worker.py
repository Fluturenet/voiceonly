# app/worker.py - Modifica le funzioni che usano il database

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
import yt_dlp

from app.database import get_database, close_thread_connection, is_database_connected
from app.config import settings
from app.models import Video
from app.constants import (
    YDL_COMMON_OPTS, YDL_INFO_OPTS, YDL_FLAT_OPTS, YDL_DOWNLOAD_OPTS,
    YDL_BULK_DOWNLOAD_OPTS, RATE_LIMIT_CALLS_PER_MINUTE, DOWNLOAD_ARCHIVE_SUFFIX
)
from app.error_handlers import handle_download_error, handle_extraction_error

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('youtube-worker')

# Global variables
scheduler = None
scan_in_progress = False
scan_should_stop = False

# Queue for communication between threads
command_queue = queue.Queue()

# Metrics for monitoring
metrics = {
    'channels_scanned': 0,
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

class YouTubeDownloader:
    """Synchronous YouTube downloader for use in threads"""
    
    def __init__(self, download_path: Path, cookies_file: Optional[str] = None):
        self.download_path = download_path
        self.cookies_file = cookies_file
        
        # Use centralized config with cookies_file override
        self.info_opts = {**YDL_INFO_OPTS, 'cookiefile': cookies_file}
        self.flat_opts = {**YDL_FLAT_OPTS, 'cookiefile': cookies_file}
        self.download_opts = {
            **YDL_DOWNLOAD_OPTS,
            'cookiefile': cookies_file,
        }
        
        # Bulk download options (will be customized per channel)
        self.bulk_download_opts = {
            **YDL_BULK_DOWNLOAD_OPTS,
            'cookiefile': cookies_file,
        }
    
    def _extract_original_title(self, info: Dict) -> str:
        """Extract original title from video info"""
        if info.get('original_title'):
            return info['original_title']
        
        if info.get('language') and info['language'] != 'en':
            return info.get('title', 'Unknown')
        
        if info.get('track') and info.get('artist'):
            return f"{info['artist']} - {info['track']}"
        
        return info.get('title', 'Unknown')
    
    def get_channel_videos(self, channel_url: str, limit: int = 10) -> tuple:
        """Get channel info and recent videos (synchronous)"""
        try:
            # Ensure we're getting the videos tab
            if not channel_url.endswith('/videos'):
                if '/videos' not in channel_url:
                    channel_url = channel_url.rstrip('/') + '/videos'
            
            logger.debug(f"Fetching channel videos from: {channel_url}")
            
            with yt_dlp.YoutubeDL(self.flat_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                
                if info is None:
                    return {}, []
                
                channel_info = {
                    'id': info.get('channel_id'),
                    'name': info.get('channel', info.get('uploader', 'Unknown')),
                    'url': channel_url,
                    'description': info.get('description'),
                    'thumbnails': info.get('thumbnails'),
                    'thumbnail': info.get('thumbnail'),
                    'subscriber_count': info.get('channel_follower_count'),
                    'video_count': info.get('channel_video_count'),
                }
                
                videos = []
                entries = info.get('entries', [])
                
                for entry in entries[:limit]:
                    if entry and entry.get('id'):
                        videos.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Unknown'),
                            'url': f"https://youtube.com/watch?v={entry.get('id')}",
                            'duration': entry.get('duration'),
                            'upload_date': entry.get('upload_date'),
                            'view_count': entry.get('view_count'),
                            'channel': entry.get('channel', channel_info['name']),
                            'channel_id': entry.get('channel_id', channel_info['id']),
                        })
                
                return channel_info, videos
                
        except Exception as e:
            logger.error(f"Error in get_channel_videos: {e}")
            return {}, []
    
    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """Get complete video metadata (synchronous)"""
        url = f"https://youtube.com/watch?v={video_id}"
        
        try:
            with yt_dlp.YoutubeDL(self.info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info:
                    if 'original_title' not in info:
                        info['original_title'] = self._extract_original_title(info)
                    
                    if 'formats' in info:
                        audio_formats = [f for f in info['formats'] if f.get('vcodec') == 'none']
                        if audio_formats:
                            info['best_audio_format'] = audio_formats[-1]
                    
                    return info
                return None
                
        except Exception as e:
            logger.error(f"Error in get_video_metadata for {video_id}: {e}")
            return None
    
    def download_audio(self, video_id: str, channel_name: str) -> Optional[Dict]:
        """Download video audio (synchronous)"""
        url = f"https://youtube.com/watch?v={video_id}"
        channel_dir = self.download_path / channel_name
        channel_dir.mkdir(parents=True, exist_ok=True)
        
        opts = self.download_opts.copy()
        opts['outtmpl'] = str(channel_dir / '%(id)s.%(ext)s')
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    expected_file = channel_dir / f"{video_id}.opus"
                    file_size = expected_file.stat().st_size if expected_file.exists() else 0
                    
                    original_title = self._extract_original_title(info)
                    info['_original_title'] = original_title
                    
                    return {
                        'video_id': video_id,
                        'title': original_title,
                        'file_path': str(expected_file),
                        'file_size': file_size,
                        'metadata': info
                    }
                return None
                
        except Exception as e:
            logger.error(f"Error downloading {video_id}: {e}")
            return None
    
    def bulk_download_channel(self, channel_url: str, channel_name: str, limit: int = 10) -> List[Dict]:
        """
        Download all new videos from a channel using yt-dlp's download archive feature.
        yt-dlp will automatically skip already downloaded videos.
        
        Returns list of downloaded video info dicts.
        """
        channel_dir = self.download_path / channel_name
        channel_dir.mkdir(parents=True, exist_ok=True)
        
        # Create download archive file path (tracks already downloaded videos)
        archive_file = channel_dir / f"{channel_name}{DOWNLOAD_ARCHIVE_SUFFIX}"
        
        # Configure options for this channel
        opts = self.bulk_download_opts.copy()
        opts['download_archive'] = str(archive_file)
        opts['outtmpl'] = str(channel_dir / '%(id)s.%(ext)s')
        opts['playlistend'] = limit  # Limit number of videos to download
        
        # Ensure we're downloading from videos tab
        if not channel_url.endswith('/videos'):
            if '/videos' not in channel_url:
                channel_url = channel_url.rstrip('/') + '/videos'
        
        downloaded_videos = []
        
        try:
            logger.info(f"🚀 Starting bulk download for channel: {channel_name}")
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                # yt-dlp will automatically skip videos already in the archive
                info = ydl.extract_info(channel_url, download=True)
                
                if info and 'entries' in info:
                    for entry in info['entries']:
                        if entry and entry.get('id'):
                            video_id = entry['id']
                            expected_file = channel_dir / f"{video_id}.opus"
                            
                            if expected_file.exists():
                                # File was downloaded in this session
                                file_size = expected_file.stat().st_size
                                
                                downloaded_videos.append({
                                    'video_id': video_id,
                                    'title': entry.get('title', 'Unknown'),
                                    'file_path': str(expected_file),
                                    'file_size': file_size,
                                    'metadata': entry
                                })
                                
                                logger.debug(f"✅ Downloaded in bulk: {entry.get('title', video_id)}")
                            else:
                                logger.debug(f"⏭️ Skipped (already downloaded): {video_id}")
                
                logger.info(f"📦 Bulk download completed for {channel_name}: {len(downloaded_videos)} new videos")
                
        except Exception as e:
            logger.error(f"Error in bulk download for {channel_name}: {e}")
        
        return downloaded_videos

# Thread worker function
def worker_thread():
    """Main worker thread function"""
    global scan_in_progress, scan_should_stop, metrics
    
    logger.info(f"Worker thread {threading.get_ident()} started")
    
    try:
        # Initialize downloader in this thread
        cookies_file = settings.COOKIES_FILE if hasattr(settings, 'COOKIES_FILE') else None
        downloader = YouTubeDownloader(settings.DOWNLOAD_PATH, cookies_file)
        
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
    """Scan a single channel (runs downloader in thread)"""
    global scan_should_stop, metrics
    
    db = get_database()
    
    channel_name_raw = channel.get('name') or channel.get('channel_id') or 'Unknown'
    channel_name = sanitize_filename(channel_name_raw)
    
    logger.info(f"🔍 Scanning channel: {channel_name}")
    
    # Get channel info and videos (runs in thread via run_in_executor)
    loop = asyncio.get_event_loop()
    channel_info, videos = await loop.run_in_executor(
        None,
        downloader.get_channel_videos,
        channel['url'],
        10
    )
    
    if scan_should_stop:
        logger.info(f"Scan stopped during channel {channel_name}")
        return
    
    if not channel_info:
        logger.warning(f"No channel info returned for {channel_name}")
        return
    
    # Update channel info in DB
    await update_channel_info_db(db, channel, channel_info)
    
    # Bulk download new videos (yt-dlp handles duplicate detection)
    logger.info(f"📥 Starting bulk download for {channel_name}...")
    
    downloaded_videos = await loop.run_in_executor(
        None,
        downloader.bulk_download_channel,
        channel['url'],
        channel_name,
        10  # Max 10 videos per channel scan
    )
    
    if not downloaded_videos:
        logger.info(f"No new videos downloaded for {channel_name}")
    else:
        logger.info(f"Downloaded {len(downloaded_videos)} new videos for {channel_name}")
        
        # Process each downloaded video
        for video_result in downloaded_videos:
            try:
                video_id = video_result['video_id']
                
                # Get full metadata for the downloaded video
                full_metadata = await loop.run_in_executor(
                    None,
                    downloader.get_video_metadata,
                    video_id
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
                    full_metadata=full_metadata or video_result['metadata']
                )
                
                metrics['videos_downloaded'] += 1
                metrics['total_download_size'] += video_result['file_size']
                
                logger.info(f"✅ Processed: {video_result['title']} ({video_result['file_size'] / 1024 / 1024:.1f} MB)")
                
            except Exception as e:
                logger.error(f"Error processing downloaded video {video_result.get('video_id')}: {e}")
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