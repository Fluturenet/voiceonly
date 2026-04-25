# app/util/youtube/url_builder.py
"""Utility functions for building robust YouTube channel tab URLs."""

from typing import Literal


# Known tab suffixes that may already be appended to a channel URL.
_TAB_SUFFIXES = ("/videos", "/streams")


def build_channel_tab_url(channel_url: str, tab: Literal["videos", "streams"]) -> str:
    """Return the channel URL pointing at the given tab.

    The function is idempotent: if *channel_url* already ends with the
    requested tab suffix (``/videos`` or ``/streams``) it is returned
    unchanged.  Any *other* existing tab suffix is first stripped before
    the requested one is appended.

    Args:
        channel_url: Base channel URL (may or may not include a tab suffix).
        tab: Which tab to target – either ``"videos"`` or ``"streams"``.

    Returns:
        A normalised URL with the requested tab suffix.

    Examples:
        >>> build_channel_tab_url("https://youtube.com/@Example", "videos")
        'https://youtube.com/@Example/videos'
        >>> build_channel_tab_url("https://youtube.com/@Example/streams", "videos")
        'https://youtube.com/@Example/videos'
        >>> build_channel_tab_url("https://youtube.com/@Example/videos", "videos")
        'https://youtube.com/@Example/videos'
    """
    suffix = f"/{tab}"
    base = channel_url.rstrip("/")

    # Strip any existing tab suffix so we don't duplicate or stack them.
    for known in _TAB_SUFFIXES:
        if base.endswith(known):
            base = base[: -len(known)]
            break

    return base + suffix
