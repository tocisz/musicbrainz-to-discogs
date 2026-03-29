"""Discogs API client."""

import time

import requests

API_URL = "https://api.discogs.com"
RATE_LIMIT_DELAY = 1.0


class DiscogsClient:
    def __init__(self, token: str, username: str):
        self.token = token
        self.username = username
        self._headers = {
            "Authorization": f"Discogs token={token}",
            "User-Agent": "MBSync/1.0 (music-sync)",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        time.sleep(RATE_LIMIT_DELAY)
        resp = requests.get(f"{API_URL}{path}", params=params, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str) -> requests.Response:
        time.sleep(RATE_LIMIT_DELAY)
        return requests.post(f"{API_URL}{path}", headers=self._headers)

    def get_identity(self) -> dict:
        return self._get("/oauth/identity")

    def get_collection_releases(self) -> list[int]:
        """Get all release IDs already in collection."""
        ids = []
        page = 1

        while True:
            data = self._get(
                f"/users/{self.username}/collection/folders/0/releases",
                {"per_page": 100, "page": page},
            )
            for item in data.get("releases", []):
                ids.append(item["id"])

            if page >= data["pagination"]["pages"]:
                break
            page += 1

        return ids

    def search_by_barcode(self, barcode: str) -> int | None:
        """Search by barcode, return release ID or None."""
        if not barcode:
            return None

        data = self._get(
            "/database/search",
            {"barcode": barcode, "type": "release", "per_page": 5},
        )

        results = data.get("results", [])
        if not results:
            return None

        # Prefer CD format
        for r in results:
            if "CD" in r.get("format", []):
                return r["id"]
        return results[0]["id"]

    def search_by_query(self, artist: str, title: str) -> int | None:
        """Search by artist + title, return release ID or None."""
        import re

        query = re.sub(r"\s+", " ", f"{artist} {title}").strip()

        data = self._get(
            "/database/search",
            {"q": query, "type": "release", "per_page": 5},
        )

        results = data.get("results", [])
        if not results:
            return None

        # Prefer CD format
        for r in results:
            if "CD" in r.get("format", []):
                return r["id"]
        return results[0]["id"]

    def add_to_collection(self, release_id: int) -> bool:
        """Add release to collection. Returns True on success."""
        resp = self._post(
            f"/users/{self.username}/collection/folders/0/releases/{release_id}"
        )
        return resp.status_code == 201
