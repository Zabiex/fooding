"""Blocking Instagram media download helpers."""

from __future__ import annotations

from pathlib import Path

import yt_dlp


def download_instagram_video(url: str, output_path: str, *, max_bytes: int) -> str:
    """Download one Instagram video to ``output_path`` and return its path."""
    options = {
        "format": "mp4/best",
        "outtmpl": output_path,
        "max_filesize": max_bytes,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.download([url])

    path = Path(output_path)
    if not path.is_file():
        raise RuntimeError("Instagram did not provide a video file")
    return str(path)