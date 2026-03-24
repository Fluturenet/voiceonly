# app/models.py
from datetime import datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field, field_validator
from pydantic_core import core_schema
from bson import ObjectId
import re

# Custom ObjectId type for Pydantic v2
class PyObjectId:
    """Custom type for handling MongoDB ObjectId in Pydantic v2"""
    
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler) -> core_schema.CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema([
                core_schema.is_instance_schema(ObjectId),
                core_schema.chain_schema([
                    core_schema.str_schema(),
                    core_schema.no_info_plain_validator_function(cls.validate),
                ])
            ]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x)
            ),
        )
    
    @classmethod
    def validate(cls, v: str) -> ObjectId:
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

class Channel(BaseModel):
    """YouTube channel to monitor"""
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    url: str
    name: Optional[str] = None  # YouTube channel name
    friendly_name: Optional[str] = None  # Custom short name chosen by user
    channel_id: Optional[str] = None  # YouTube channel ID (UC...)
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    uploader_id: Optional[str] = None
    uploader_url: Optional[str] = None
    
    # Channel stats
    subscriber_count: Optional[int] = None
    video_count: Optional[int] = None
    view_count: Optional[int] = None
    
    # Status
    active: bool = True
    last_scan: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Store complete yt-dlp info for the channel
    raw_info: Optional[Dict[str, Any]] = None
    
    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format"""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        if 'youtube.com' not in v and 'youtu.be' not in v:
            raise ValueError('URL must be a YouTube URL')
        return v
    
    @field_validator('friendly_name')
    @classmethod
    def validate_friendly_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate friendly name (alphanumeric + hyphens only)"""
        if v is not None:
            import re
            if not re.match(r'^[a-zA-Z0-9_-]+$', v):
                raise ValueError('Friendly name can only contain letters, numbers, hyphens and underscores')
            if len(v) > 50:
                raise ValueError('Friendly name too long (max 50 chars)')
        return v
    
    class Config:
        arbitrary_types_allowed = True
        populate_by_name = True
        json_encoders = {ObjectId: str}
        json_schema_extra = {
            "example": {
                "url": "https://youtube.com/c/ExampleChannel",
                "name": "Example Channel",
                "friendly_name": "example",
                "active": True
            }
        }

# Video model enhanced - stores ALL metadata from yt-dlp
class Video(BaseModel):
    """Downloaded video/audio with complete metadata"""
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    
    # Core identifiers
    video_id: str  # YouTube video ID
    channel_id: str  # Reference to channel
    channel_name: str
    channel_url: Optional[str] = None
    
    # Basic info
    title: str
    description: Optional[str] = None
    duration: int  # In seconds
    upload_timestamp: float  # Unix timestamp when video was published
    download_date: Optional[datetime] = None  # When we downloaded it
    
    # File info
    file_path: Optional[str] = None
    file_size: Optional[int] = None  # In bytes
    downloaded: bool = False
    
    # Thumbnails (multiple qualities available)
    thumbnails: Optional[List[Dict[str, Any]]] = None
    thumbnail_url: Optional[str] = None  # Best quality thumbnail
    
    # YouTube specific fields
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None
    uploader_url: Optional[str] = None
    
    # Stats
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    
    # Availability & restrictions
    availability: Optional[str] = None  # 'public', 'unlisted', 'private', etc.
    is_live: Optional[bool] = None
    was_live: Optional[bool] = None
    
    # Chapters/timestamps if available
    chapters: Optional[List[Dict[str, Any]]] = None
    
    # Format info (audio details)
    format_id: Optional[str] = None
    format_note: Optional[str] = None
    audio_bitrate: Optional[float] = None  # <-- CAMBIATO da int a float
    audio_codec: Optional[str] = None
    filesize_approx: Optional[int] = None
    
    # Age restriction
    age_limit: Optional[int] = None
    
    # Categories/tags
    categories: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    
    # Store the complete yt-dlp info dict for future use
    raw_info: Optional[Dict[str, Any]] = None
    
    # Aggiungiamo un validator per gestire conversioni
    @field_validator('audio_bitrate', mode='before')
    @classmethod
    def validate_audio_bitrate(cls, v):
        """Convert audio_bitrate to float, handling various input types"""
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    
    @field_validator('duration', mode='before')
    @classmethod
    def validate_duration(cls, v):
        """Ensure duration is int"""
        if v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    
    class Config:
        arbitrary_types_allowed = True
        populate_by_name = True
        json_encoders = {ObjectId: str}
        json_schema_extra = {
            "example": {
                "video_id": "dQw4w9WgXcQ",
                "channel_id": "UC...",
                "title": "Example Video",
                "duration": 367,
                "upload_date": "2024-01-01T00:00:00"
            }
        }

# Models for API requests/responses
class ChannelCreate(BaseModel):
    """Model for creating a new channel"""
    url: str
    
    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format"""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        if 'youtube.com' not in v and 'youtu.be' not in v:
            raise ValueError('URL must be a YouTube URL')
        return v

class ChannelResponse(BaseModel):
    """Model for channel response (public view)"""
    id: str
    url: str
    name: Optional[str]
    description: Optional[str]
    thumbnail_url: Optional[str]
    active: bool
    video_count: Optional[int] = 0
    subscriber_count: Optional[int] = None
    last_scan: Optional[datetime]
    created_at: datetime
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "url": "https://youtube.com/c/ExampleChannel",
                "name": "Example Channel",
                "active": True,
                "video_count": 42
            }
        }

class VideoResponse(BaseModel):
    """Model for video response (public view)"""
    id: str
    video_id: str
    title: str
    description: Optional[str]
    duration: int
    upload_date: datetime
    download_date: Optional[datetime]
    channel_name: str
    channel_id: str
    thumbnail_url: Optional[str]
    file_size: Optional[int]
    view_count: Optional[int]
    like_count: Optional[int]
    
    class Config:
        json_schema_extra = {
            "example": {
                "video_id": "dQw4w9WgXcQ",
                "title": "Never Gonna Give You Up",
                "duration": 367,
                "channel_name": "Rick Astley"
            }
        }

# Model for podcast feed filtering options
class PodcastFilterOptions(BaseModel):
    """Options for filtering videos in podcast feed"""
    max_results: Optional[int] = 50
    include_descriptions: bool = True
    include_chapters: bool = False
    min_duration: Optional[int] = None  # Minimum duration in seconds
    max_duration: Optional[int] = None  # Maximum duration in seconds
    days_old: Optional[int] = None  # Only videos from last X days
    sort_by: str = "upload_date"  # upload_date, popularity, duration
    sort_order: str = "desc"  # asc or desc
    
    @field_validator('sort_by')
    @classmethod
    def validate_sort_by(cls, v: str) -> str:
        valid_fields = ["upload_date", "download_date", "duration", "view_count", "like_count"]
        if v not in valid_fields:
            raise ValueError(f"sort_by must be one of {valid_fields}")
        return v
    
    @field_validator('sort_order')
    @classmethod
    def validate_sort_order(cls, v: str) -> str:
        if v not in ["asc", "desc"]:
            raise ValueError("sort_order must be 'asc' or 'desc'")
        return v

# Model for iTunes podcast feed
class ITunesPodcastFeed(BaseModel):
    """iTunes-compatible podcast feed data"""
    title: str
    description: str
    author: str
    image_url: str
    category: str = "Music"  # Default category
    explicit: bool = False
    language: str = "it"
    copyright: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    website_url: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "My YouTube Podcast",
                "description": "Audio from my favorite YouTube channels",
                "author": "Me",
                "image_url": "https://example.com/podcast.jpg",
                "language": "it"
            }
        }
