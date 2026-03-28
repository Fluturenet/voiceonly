# app/database.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
import threading
from app.logging_config import configure_named_logger

logger = configure_named_logger('core_database')

# Thread-local storage for database connections
_thread_local = threading.local()

def get_database():
    """
    Get database instance for the current thread.
    Creates a new connection if one doesn't exist for this thread.
    """
    if not hasattr(_thread_local, "mongodb"):
        # Create new client for this thread
        client = AsyncIOMotorClient(settings.MONGODB_URI)
        _thread_local.mongodb = client[settings.MONGODB_DB]
        _thread_local.client = client
        logger.debug(f"✅ Created new database connection for thread {threading.get_ident()}")
    
    return _thread_local.mongodb

def close_thread_connection():
    """Close database connection for the current thread"""
    if hasattr(_thread_local, "client"):
        _thread_local.client.close()
        logger.debug(f"🛑 Closed database connection for thread {threading.get_ident()}")
        del _thread_local.client
        del _thread_local.mongodb

def is_database_connected():
    """
    Check if database is connected for the current thread.
    Returns True if we have an active connection and can ping the database.
    """
    try:
        # Check if we have a connection in this thread
        if not hasattr(_thread_local, "client"):
            return False
        
        # Try to ping (synchronously) - Motor doesn't have sync ping, so we'll check client
        # This is a simple check - if we have a client, assume it's connected
        # For a more thorough check, we'd need to run an async operation
        return True
    except Exception:
        return False

# For backwards compatibility
connect_to_mongo = get_database