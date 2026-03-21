# app/error_handlers.py
"""Centralized error handling utilities"""

import logging
import yt_dlp
from typing import Callable, Any

logger = logging.getLogger('voiceonly')


def handle_download_error(error: Exception, video_id: str, channel_name: str) -> bool:
    """
    Handle download errors with appropriate logging and return recovery suggestion
    Returns: True if retryable, False if not
    """
    if isinstance(error, yt_dlp.utils.DownloadError):
        logger.warning(f"YouTube blocked download for '{video_id}' in {channel_name}: {error}")
        return False  # Don't retry - YouTube has blocked this
    elif isinstance(error, yt_dlp.utils.ExtractorError):
        logger.warning(f"Video extraction error for '{video_id}': {error}")
        return False  # Video might be private, age-restricted, etc
    elif isinstance(error, (ConnectionError, TimeoutError, OSError)):
        logger.warning(f"Network error downloading '{video_id}': {error}")
        return True  # Retryable network error
    else:
        logger.error(f"Unexpected error downloading '{video_id}': {error}", exc_info=True)
        return False


def handle_extraction_error(error: Exception, url: str) -> bool:
    """
    Handle channel/video info extraction errors
    Returns: True if retryable, False if not
    """
    if isinstance(error, yt_dlp.utils.ExtractorError):
        logger.warning(f"Cannot extract info from {url}: {error}")
        return False  # Channel/video likely doesn't exist or is private
    elif isinstance(error, (ConnectionError, TimeoutError)):
        logger.warning(f"Network error extracting from {url}: {error}")
        return True  # Retryable network error
    else:
        logger.error(f"Unexpected extraction error from {url}: {error}", exc_info=True)
        return False


def handle_database_error(error: Exception, operation: str) -> bool:
    """
    Handle database operation errors
    Returns: True if retryable, False if not
    """
    if isinstance(error, ConnectionError):
        logger.error(f"Database connection error during {operation}: {error}")
        return True  # Retryable connection error
    elif isinstance(error, Exception) and "duplicate" in str(error).lower():
        logger.debug(f"Duplicate entry during {operation}: {error}")
        return False  # Don't retry duplicate key errors
    else:
        logger.error(f"Database error during {operation}: {error}", exc_info=True)
        return False


def safe_operation(func: Callable, *args, **kwargs) -> tuple[Any, Exception]:
    """
    Safely execute an operation and return result and exception
    Returns: (result, error) where one is None if successful
    """
    try:
        result = func(*args, **kwargs)
        return result, None
    except Exception as e:
        return None, e
