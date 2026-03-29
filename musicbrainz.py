"""MusicBrainz API client."""

import time

import requests

from models import Release

API_URL = "https://musicbrainz.org/ws/2"
USER_AGENT = "MBSync/1.0 (music-sync)"
RATE_LIMIT_DELAY = 1.1  # max 1 req/sec


class MusicBrainzClient:
    def __init__(self, collection_id: str):
        self.collection_id = collection_id

    def _get(self, path: str, params: dict = None) -> dict:
        time.sleep(RATE_LIMIT_DELAY)
        resp = requests.get(
            f"{API_URL}{path}",
            params={**(params or {}), "fmt": "json"},
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return resp.json()

    def get_collection_info(self) -> dict:
        return self._get(f"/collection/{self.collection_id}")

    def get_collection_releases(self) -> list[Release]:
        """Fetch all releases with artist credits and URL relations."""
        releases = []
        offset = 0

        info = self.get_collection_info()
        total = info["release-count"]

        while offset < total:
            data = self._get(
                "/release",
                {
                    "collection": self.collection_id,
                    "inc": "artist-credits+url-rels",
                    "limit": 100,
                    "offset": offset,
                },
            )

            for r in data.get("releases", []):
                releases.append(self._parse_release(r))

            offset += len(data.get("releases", []))

        return releases

    def _parse_release(self, r: dict) -> Release:
        # Extract artist from artist-credit
        artist = ""
        if "artist-credit" in r:
            parts = []
            for ac in r["artist-credit"]:
                if isinstance(ac, str):
                    parts.append(ac)
                else:
                    parts.append(ac["artist"]["name"])
            artist = "".join(parts)

        # Find Discogs URL
        discogs_url = None
        for rel in r.get("relations", []):
            if rel.get("type") == "discogs":
                discogs_url = rel["url"]["resource"]
                break

        return Release(
            mbid=r["id"],
            title=r["title"],
            artist=artist,
            date=r.get("date", ""),
            barcode=r.get("barcode", ""),
            discogs_url=discogs_url,
        )
