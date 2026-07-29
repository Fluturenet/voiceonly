# app/util/youtube/yt_dlp_client.py
"""Reusable adapter around yt_dlp for downloading YouTube audio.

This module is the **only** place in the application that imports ``yt_dlp``
directly.  All other modules that need YouTube extraction/download
functionality should go through :class:`YtDlpClient`.
"""

import logging
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import yt_dlp

from app.constants import (
    YDL_INFO_OPTS,
    YDL_FLAT_OPTS,
    YDL_DOWNLOAD_OPTS,
    YDL_BULK_DOWNLOAD_OPTS,
    DOWNLOAD_ARCHIVE_SUFFIX,
)

logger = logging.getLogger(__name__)


class YtDlpClient:
    """Synchronous YouTube downloader / metadata extractor.

    Designed to be instantiated once per worker thread and reused for all
    operations within that thread.  All methods are *synchronous* and must
    be called via ``loop.run_in_executor`` when used from async code.

    Args:
        download_path: Root directory under which per-channel sub-directories
            will be created.
        cookies_file: Optional path to a Netscape-format cookies file.
    """

    def __init__(self, download_path: Path, cookies_file: Optional[str] = None):
        self.download_path = download_path
        self.cookies_file = cookies_file

        # Build per-instance option dicts once, incorporating cookies_file.
        self._info_opts: Dict = {**YDL_INFO_OPTS, "cookiefile": cookies_file}
        self._flat_opts: Dict = {**YDL_FLAT_OPTS, "cookiefile": cookies_file}
        self._download_opts: Dict = {**YDL_DOWNLOAD_OPTS, "cookiefile": cookies_file}
        self._bulk_download_opts: Dict = {
            **YDL_BULK_DOWNLOAD_OPTS,
            "cookiefile": cookies_file,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_original_title(info: Dict) -> str:
        """Return the most descriptive title available in *info*."""
        if info.get("original_title"):
            return info["original_title"]
        if info.get("language") and info["language"] != "en":
            return info.get("title", "Unknown")
        if info.get("track") and info.get("artist"):
            return f"{info['artist']} - {info['track']}"
        return info.get("title", "Unknown")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_channel_entries(
        self,
        channel_url: str,
        limit: int = 10,
    ) -> Tuple[Dict, List[Dict]]:
        """Extract channel metadata and the most-recent *limit* entries.

        Args:
            channel_url: Fully-qualified channel URL, **including** the tab
                suffix (e.g. ``…/videos`` or ``…/streams``).  Use
                :func:`app.util.youtube.url_builder.build_channel_tab_url`
                to construct it.
            limit: Maximum number of entries to return.

        Returns:
            A ``(channel_info, entries)`` tuple.  Both are empty on error.
        """
        logger.debug("Fetching channel entries from: %s", channel_url)
        try:
            with yt_dlp.YoutubeDL(self._flat_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

            if info is None:
                return {}, []

            channel_info: Dict = {
                "id": info.get("channel_id"),
                "name": info.get("channel", info.get("uploader", "Unknown")),
                "url": channel_url,
                "description": info.get("description"),
                "thumbnails": info.get("thumbnails"),
                "thumbnail": info.get("thumbnail"),
                "subscriber_count": info.get("channel_follower_count"),
                "video_count": info.get("channel_video_count"),
            }

            entries: List[Dict] = []
            for entry in (info.get("entries") or [])[:limit]:
                if entry and entry.get("id"):
                    entries.append(
                        {
                            "id": entry.get("id"),
                            "title": entry.get("title", "Unknown"),
                            "url": f"https://youtube.com/watch?v={entry.get('id')}",
                            "duration": entry.get("duration"),
                            "upload_date": entry.get("upload_date"),
                            "view_count": entry.get("view_count"),
                            "channel": entry.get("channel", channel_info["name"]),
                            "channel_id": entry.get("channel_id", channel_info["id"]),
                        }
                    )

            return channel_info, entries

        except Exception:
            logger.exception("Error in get_channel_entries for %s", channel_url)
            return {}, []

    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """Return complete metadata for a single video.

        Args:
            video_id: YouTube video ID (11-character string).

        Returns:
            A metadata dict on success, ``None`` on error.
        """
        url = f"https://youtube.com/watch?v={video_id}"
        try:
            with yt_dlp.YoutubeDL(self._info_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if info is None:
                return None

            if "original_title" not in info:
                info["original_title"] = self._extract_original_title(info)

            if "formats" in info:
                audio_formats = [
                    f for f in info["formats"] if f.get("vcodec") == "none"
                ]
                if audio_formats:
                    info["best_audio_format"] = audio_formats[-1]

            return info

        except Exception:
            logger.exception("Error in get_video_metadata for %s", video_id)
            return None

    def bulk_download_channel_tab(
        self,
        source_url: str,
        channel_name: str,
        limit: int = 10,
    ) -> List[Dict]:
        """Bulk-download audio from *source_url* using yt-dlp's archive file.

        yt-dlp automatically skips videos that are already present in the
        download archive, making subsequent calls idempotent.

        Args:
            source_url: Fully-qualified URL to download from (channel tab or
                playlist URL).  The caller is responsible for constructing the
                correct URL via :func:`app.util.youtube.url_builder.build_channel_tab_url`.
            channel_name: Sanitised channel name used to create the
                per-channel sub-directory under :attr:`download_path`.
            limit: Maximum number of videos to attempt to download
                (``playlistend``).

        Returns:
            List of dicts describing *newly* downloaded files.  Each dict has
            the keys ``video_id``, ``title``, ``file_path``, ``file_size``,
            and ``metadata``.
        """
        channel_dir = self.download_path / channel_name
        channel_dir.mkdir(parents=True, exist_ok=True)

        archive_file = channel_dir / f"{channel_name}{DOWNLOAD_ARCHIVE_SUFFIX}"

        opts = self._bulk_download_opts.copy()
        opts["download_archive"] = str(archive_file)
        opts["outtmpl"] = str(channel_dir / "%(id)s.%(ext)s")
        opts["playlistend"] = limit

        downloaded_videos: List[Dict] = []

        try:
            logger.info("🚀 Starting bulk download for channel: %s (%s)", channel_name, source_url)

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source_url, download=True)

            if info and "entries" in info:
                for entry in info["entries"]:
                    if not (entry and entry.get("id")):
                        continue
                    video_id = entry["id"]
                    expected_file = channel_dir / f"{video_id}.opus"

                    if expected_file.exists():
                        file_size = expected_file.stat().st_size
                        downloaded_videos.append(
                            {
                                "video_id": video_id,
                                "title": entry.get("title", "Unknown"),
                                "file_path": str(expected_file),
                                "file_size": file_size,
                                "metadata": entry,
                            }
                        )
                        logger.debug("✅ Downloaded in bulk: %s", entry.get("title", video_id))
                    else:
                        logger.debug("⏭️ Skipped (already downloaded): %s", video_id)

            logger.info(
                "📦 Bulk download completed for %s: %d new videos",
                channel_name,
                len(downloaded_videos),
            )

        except Exception:
            logger.exception("Error in bulk_download_channel_tab for %s", channel_name)

        return downloaded_videos

    # ------------------------------------------------------------------
    # Legacy compatibility shims
    # ------------------------------------------------------------------

    def get_channel_videos(self, channel_url: str, limit: int = 10) -> Tuple[Dict, List[Dict]]:
        """Thin shim that calls :meth:`get_channel_entries` on the ``/videos`` tab.

        .. deprecated::
            Prefer :meth:`get_channel_entries` with an explicit tab URL built
            via :func:`app.util.youtube.url_builder.build_channel_tab_url`.
        """
        from app.util.youtube.url_builder import build_channel_tab_url
        videos_url = build_channel_tab_url(channel_url, "videos")
        return self.get_channel_entries(videos_url, limit=limit)

    def bulk_download_channel(
        self, channel_url: str, channel_name: str, limit: int = 10
    ) -> List[Dict]:
        """Thin shim that calls :meth:`bulk_download_channel_tab` on the ``/videos`` tab.

        .. deprecated::
            Prefer :meth:`bulk_download_channel_tab` with an explicit tab URL.
        """
        from app.util.youtube.url_builder import build_channel_tab_url
        videos_url = build_channel_tab_url(channel_url, "videos")
        return self.bulk_download_channel_tab(videos_url, channel_name, limit=limit)
