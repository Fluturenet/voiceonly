# app/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import uvicorn
import logging

from fastapi.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.logging_config import configure_named_logger, configure_uvicorn_loggers
from app.routes import admin, podcast, download

logger = configure_named_logger('voiceonly')
configure_uvicorn_loggers()

logging.getLogger("watchfiles").setLevel(logging.WARNING)

# In app/main.py
from app.worker import start_worker, shutdown_worker
from app.database import close_thread_connection

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handle startup and shutdown events
    """
    # Startup
    logger.info("🚀 Starting up...")
    
    # Main thread gets its own connection
    from app.database import get_database
    db = get_database()
    
    try:
        await db.command('ping')
        logger.info("✅ Database ping successful")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        raise
    
    # Start worker thread (will create its own connection)
    start_worker()
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    shutdown_worker()
    
    # Close main thread's connection
    close_thread_connection()

# Create FastAPI app
_root_path = settings.PROXY_PATH if settings.BEHIND_PROXY else ""
app = FastAPI(
    title="VoiceOnly",
    description="Convert YouTube channels to private podcasts",
    version="1.0.0",
    lifespan=lifespan,
    root_path=_root_path
)

# When running behind a reverse proxy, trust forwarded headers
if settings.BEHIND_PROXY:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    logger.info(f"🔀 Running behind proxy, root_path='{_root_path}'")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(podcast.router, prefix="/podcast", tags=["podcast"])
app.include_router(download.router, prefix="/download", tags=["download"])

@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to admin panel"""
    return """
    <html>
        <head>
            <title>VoiceOnly</title>
            <meta http-equiv="refresh" content="0; URL=/admin" />
        </head>
        <body>
            <p>Redirecting to <a href="/admin">admin panel</a>...</p>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        log_level="info"
    )

