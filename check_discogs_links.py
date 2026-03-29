#!/usr/bin/env python3
"""Check which releases in a MusicBrainz collection have Discogs links."""

import requests
import time
import re
from dataclasses import dataclass

COLLECTION_ID = "613e2f76-b3ba-4483-9b5f-0779bc66d663"
MB_API = "https://musicbrainz.org/ws/2"
USER_AGENT = "MBCollectionChecker/1.0 (music-sync)"
RATE_LIMIT_DELAY = 1.1  # MusicBrainz requires max 1 req/sec


@dataclass
class Release:
    mbid: str
    title: str
    artist: str
    date: str
    barcode: str
    discogs_url: str | None = None

    @property
    def discogs_id(self) -> str | None:
        if self.discogs_url:
            match = re.search(r"/release/(\d+)", self.discogs_url)
            return match.group(1) if match else None
        return None


def mb_get(path: str, params: dict = None) -> dict:
    """Make a rate-limited GET request to MusicBrainz API."""
    time.sleep(RATE_LIMIT_DELAY)
    resp = requests.get(
        f"{MB_API}{path}",
        params={**(params or {}), "fmt": "json"},
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json()


def get_collection_releases() -> list[Release]:
    """Fetch all releases from the collection with artist credits."""
    releases = []
    offset = 0
    limit = 100

    while True:
        data = mb_get(
            f"/release",
            {
                "collection": COLLECTION_ID,
                "inc": "artist-credits+url-rels",
                "limit": limit,
                "offset": offset,
            },
        )

        for r in data.get("releases", []):
            # Extract primary artist from artist-credit
            artist = ""
            if "artist-credit" in r:
                artist = r["artist-credit"][0]["artist"]["name"]
                # Handle joined credits (e.g. "Artist & Artist")
                for ac in r["artist-credit"][1:]:
                    if isinstance(ac, str):
                        artist += ac
                    else:
                        artist += ac["artist"]["name"]

            # Find Discogs URL
            discogs_url = None
            for rel in r.get("relations", []):
                if rel.get("type") == "discogs":
                    discogs_url = rel["url"]["resource"]
                    break

            releases.append(
                Release(
                    mbid=r["id"],
                    title=r["title"],
                    artist=artist,
                    date=r.get("date", ""),
                    barcode=r.get("barcode", ""),
                    discogs_url=discogs_url,
                )
            )

        offset += len(data.get("releases", []))
        if offset >= data.get("release-count", 0):
            break

    return releases


def main():
    print(f"Fetching releases from collection {COLLECTION_ID}...")

    # First get total count
    coll_info = mb_get(f"/collection/{COLLECTION_ID}")
    total = coll_info["release-count"]
    print(f"Collection: {coll_info['name']} ({coll_info['editor']}) - {total} releases\n")

    releases = get_collection_releases()

    with_discogs = [r for r in releases if r.discogs_url]
    without_discogs = [r for r in releases if not r.discogs_url]

    # Print results
    print("=" * 70)
    print(f"RELEASES WITH DISCOGS LINK ({len(with_discogs)}/{len(releases)})")
    print("=" * 70)
    for r in with_discogs:
        print(f"  ✓ {r.artist} - {r.title}")
        print(f"    MB: {r.mbid}")
        print(f"    Discogs: {r.discogs_url} (ID: {r.discogs_id})")
        print()

    print("=" * 70)
    print(f"RELEASES WITHOUT DISCOGS LINK ({len(without_discogs)}/{len(releases)})")
    print("=" * 70)
    for r in without_discogs:
        print(f"  ✗ {r.artist} - {r.title} ({r.date})")
        print(f"    MB: {r.mbid}")
        print(f"    Barcode: {r.barcode or 'N/A'}")
        print()

    print(f"\nSummary: {len(with_discogs)} linked, {len(without_discogs)} unlinked")


if __name__ == "__main__":
    main()
