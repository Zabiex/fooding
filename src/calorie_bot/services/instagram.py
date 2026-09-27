"""Instagram media download through the Apify Instagram scraper."""

from __future__ import annotations

from typing import Any

import httpx


APIFY_RUN_URL = "https://api.apify.com/v2/actors/apify~instagram-scraper/runs"
APIFY_DATASET_URL = "https://api.apify.com/v2/datasets/{dataset_id}/items"


async def resolve_instagram_video_url(
    url: str,
    *,
    api_token: str | None = None,
) -> str:
    """Scrape one public Instagram URL and return its direct video URL."""
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
        return stream_url


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