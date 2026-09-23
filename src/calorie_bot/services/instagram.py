"""Instagram media download through the account-free Cobalt API."""

from __future__ import annotations

from pathlib import Path

import httpx


COBALT_API_URL = "https://api.cobalt.tools/api/json"


async def download_instagram_video(url: str, output_path: str, *, max_bytes: int) -> str:
    """Resolve an Instagram URL with Cobalt and stream the MP4 to disk."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = {"url": url, "videoQuality": "720"}

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.post(COBALT_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        stream_url = data.get("url")
        if not stream_url:
            message = data.get("text", "Cobalt could not fetch that Instagram video")
            raise RuntimeError(str(message))

        async with client.stream("GET", stream_url) as video_response:
            video_response.raise_for_status()
            content_length = video_response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise RuntimeError("The Instagram video is too large to process")

            path = Path(output_path)
            written = 0
            with path.open("wb") as output:
                async for chunk in video_response.aiter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        raise RuntimeError("The Instagram video is too large to process")
                    output.write(chunk)

    if not path.is_file():
        raise RuntimeError("Instagram did not provide a video file")
    return str(path)