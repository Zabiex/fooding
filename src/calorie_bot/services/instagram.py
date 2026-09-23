"""Instagram media download through the Apify Instagram scraper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


APIFY_RUN_URL = "https://api.apify.com/v2/actors/apify~instagram-scraper/runs"
APIFY_DATASET_URL = "https://api.apify.com/v2/datasets/{dataset_id}/items"


async def download_instagram_video(
    url: str,
    output_path: str,
    *,
    max_bytes: int,
    api_token: str | None = None,
) -> str:
    """Scrape one public Instagram URL and stream its video to disk."""
    if not api_token:
        raise RuntimeError("APIFY_API_TOKEN is not configured")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_token}",
    }
    results_type = "reels" if "/reel/" in url or "/reels/" in url else "posts"
    payload = {"resultsType": results_type, "directUrls": [url], "resultsLimit": 1}

    timeout = httpx.Timeout(150.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(
            APIFY_RUN_URL,
            params={"waitForFinish": 120},
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        run_data = response.json().get("data", {})
        dataset_id = run_data.get("defaultDatasetId")
        if not dataset_id:
            raise RuntimeError("Apify did not return a result dataset")

        dataset_response = await client.get(
            APIFY_DATASET_URL.format(dataset_id=dataset_id),
            params={"clean": "true", "limit": 1},
            headers=headers,
        )
        dataset_response.raise_for_status()
        items = dataset_response.json()
        stream_url = _find_video_url(items)
        if not stream_url:
            raise RuntimeError("Apify did not find a video at that Instagram URL")

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


def _find_video_url(value: Any) -> str | None:
    if isinstance(value, dict):
        video_url = value.get("videoUrl")
        if isinstance(video_url, str) and video_url.startswith(("http://", "https://")):
            return video_url
        for nested in value.values():
            found = _find_video_url(nested)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_video_url(item)
            if found:
                return found
    return None