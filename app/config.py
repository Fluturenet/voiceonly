# app/config.py
import os
from dotenv import load_dotenv
from pathlib import Path
from typing import Optional
from app.logging_config import configure_named_logger

logger = configure_named_logger('core_config')

# Load environment variables from .env file
load_dotenv()

class Settings:
    """Application settings loaded from environment variables"""

    #Debug Mode
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "False").lower() == "true"
    
    #Password
    PASSWORD: str = os.getenv("PASSWORD","changeme")
    
    #token
    TOKEN: str = os.getenv("TOKEN", "123AB567")

    # MongoDB
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB: str = os.getenv("MONGODB_DB", "youtube_podcast")
    
    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent
    DOWNLOAD_PATH: Path = Path(os.getenv("DOWNLOAD_PATH", "./downloads"))
    
    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Reverse proxy
    BEHIND_PROXY: bool = os.getenv("BEHIND_PROXY", "False").lower() == "true"
    PROXY_PATH: str = os.getenv("PROXY_PATH", "").rstrip("/")
    TRUSTED_PROXY: list = [
        h.strip() for h in os.getenv("TRUSTED_PROXY", "").split(",") if h.strip()
    ] or ["127.0.0.1", "::1", "172.16.0.0/12"]
    TRUSTED_HOSTS: list = [
        h.strip() for h in os.getenv("TRUSTED_HOSTS", "").split(",") if h.strip()
    ] or ["*"]

    # Worker settings
    SCAN_INTERVAL_HOURS: int = int(os.getenv("SCAN_INTERVAL_HOURS", "6"))
    
    # Cookies file for yt-dlp (optional)
    COOKIES_FILE: Optional[str] = os.getenv("COOKIES_FILE")
    
    def __init__(self):
        # ... existing code ...
        
        # Create cookies file if path exists
        if self.COOKIES_FILE:
            cookies_path = Path(self.COOKIES_FILE)
            cookies_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure password file exists
        if self.PASSWORD == "changeme":
            logger.warning(f"❌ No password set: default password changeme")

# Create global settings instance
settings = Settings()
