# app/constants.py
"""Centralized configuration constants for the application"""

# ===== YouTUBE-DLP COMMON OPTIONS =====
YDL_COMMON_OPTS = {
    'quiet': True,
    'no_warnings': True,
}

# Options for getting channel/video list (fast)
YDL_FLAT_OPTS = {
    **YDL_COMMON_OPTS,
    'extract_flat': True,
}

# Options for getting complete video/channel info (detailed)
YDL_INFO_OPTS = {
    **YDL_COMMON_OPTS,
    'extract_flat': False,
}

# Options for downloading audio
YDL_DOWNLOAD_OPTS = {
    **YDL_COMMON_OPTS,
    'extract_audio': True,
    'format': 'bestaudio[ext=opus]/bestaudio',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '0',  # 0 = best quality
    }],
    'embedmetadata': True,
    'addmetadata': True,
}

# Options for bulk channel download (with archive tracking)
YDL_BULK_DOWNLOAD_OPTS = {
    **YDL_COMMON_OPTS,
    'extract_audio': True,
    'format': 'bestaudio[ext=opus]/bestaudio',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '0',
    }],
    'embedmetadata': True,
    'addmetadata': True,
    'no_overwrites': True,  # Don't overwrite existing files
    'ignoreerrors': True,   # Continue on errors
    'download_archive': None,  # Will be set per channel
}

# Options for admin panel (extract channel info quickly)
YDL_ADMIN_OPTS = {
    **YDL_COMMON_OPTS,
    'extract_flat': True,
}

# ===== CACHE SETTINGS =====
FEED_CACHE_MAX_SIZE = 50  # Maximum cached feed entries
FEED_CACHE_DURATION_SECONDS = 30  # How long to keep feeds cached

# ===== RATE LIMITING SETTINGS =====
RATE_LIMIT_CALLS_PER_MINUTE = 30

# ===== DOWNLOAD SETTINGS =====
DOWNLOAD_CHUNK_SIZE = 8192  # For file streaming
AUDIO_FORMAT = 'opus'
AUDIO_EXTENSION = '.opus'
DOWNLOAD_ARCHIVE_SUFFIX = '.downloaded'  # Suffix for download archive files

# ===== ERROR MESSAGE CONSTANTS =====
ERROR_DB_NOT_CONNECTED = "Database non connesso. Verifica che MongoDB sia in esecuzione."
ERROR_CHANNEL_NOT_FOUND = "Channel not found"
ERROR_VIDEO_NOT_FOUND = "Video not found"
ERROR_AUDIO_FILE_NOT_FOUND = "Audio file not found"

# ===== LOGGING SETTINGS =====
LOG_FILE = 'worker.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
