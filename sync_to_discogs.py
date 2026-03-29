#!/usr/bin/env python3
"""Sync MusicBrainz collection to Discogs."""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# --- Config ---
COLLECTION_ID = "613e2f76-b3ba-4483-9b5f-0779bc66d663"
MB_API = "https://musicbrainz.org/ws/2"
DISCOGS_API = "https://api.discogs.com"
DISCOGS_TOKEN = os.environ["DISCOGS_PERSONAL_TOKEN"]
DISCOGS_USERNAME = "tocisz"
USER_AGENT = "MBSync/1.0 (music-sync)"
STATE_FILE = Path(__file__).parent / "sync_state.json"

# Rate limiting
MB_DELAY = 1.1  # MusicBrainz: max 1 req/sec
DISCOGS_DELAY = 1.0  # Discogs: be polite


# --- Data ---
@dataclass
class Release:
    mbid: str
    title: str
    artist: str
    date: str
    barcode: str
    discogs_url: str | None = None
    discogs_id: int | None = None
    status: str = "pending"  # pending, found, not_found, already_in_collection, added, error
    search_method: str = ""  # url, barcode, search
    error: str = ""

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


# --- API helpers ---
def mb_get(path: str, params: dict = None) -> dict:
    """Rate-limited MusicBrainz GET."""
    time.sleep(MB_DELAY)
    resp = requests.get(
        f"{MB_API}{path}",
        params={**(params or {}), "fmt": "json"},
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json()


def discogs_get(path: str, params: dict = None) -> dict:
    """Rate-limited Discogs GET."""
    time.sleep(DISCOGS_DELAY)
    resp = requests.get(
        f"{DISCOGS_API}{path}",
        params=params,
        headers={
            "Authorization": f"Discogs token={DISCOGS_TOKEN}",
            "User-Agent": USER_AGENT,
        },
    )
    resp.raise_for_status()
    return resp.json()


def discogs_post(path: str) -> requests.Response:
    """Add release to collection."""
    time.sleep(DISCOGS_DELAY)
    resp = requests.post(
        f"{DISCOGS_API}{path}",
        headers={
            "Authorization": f"Discogs token={DISCOGS_TOKEN}",
            "User-Agent": USER_AGENT,
        },
    )
    return resp


# --- MusicBrainz ---
def get_collection_releases() -> list[Release]:
    """Fetch all releases from MusicBrainz collection."""
    releases = []
    offset = 0

    coll_info = mb_get(f"/collection/{COLLECTION_ID}")
    total = coll_info["release-count"]
    print(f"Collection: {coll_info['name']} - {total} releases")

    while offset < total:
        data = mb_get(
            "/release",
            {
                "collection": COLLECTION_ID,
                "inc": "artist-credits+url-rels",
                "limit": 100,
                "offset": offset,
            },
        )

        for r in data.get("releases", []):
            # Extract artist
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

    return releases


# --- Discogs ---
def search_discogs_by_barcode(barcode: str) -> int | None:
    """Search Discogs by barcode, return release ID or None."""
    if not barcode:
        return None

    data = discogs_get(
        "/database/search",
        {"barcode": barcode, "type": "release", "per_page": 5},
    )

    results = data.get("results", [])
    if results:
        # Prefer CD format if multiple results
        for r in results:
            if "CD" in r.get("format", []):
                return r["id"]
        return results[0]["id"]
    return None


def search_discogs_by_query(artist: str, title: str) -> int | None:
    """Search Discogs by artist + title, return release ID or None."""
    # Clean up artist name for search
    query = f"{artist} {title}"
    query = re.sub(r"\s+", " ", query).strip()

    data = discogs_get(
        "/database/search",
        {"q": query, "type": "release", "per_page": 5},
    )

    results = data.get("results", [])
    if results:
        # Prefer CD format
        for r in results:
            if "CD" in r.get("format", []):
                return r["id"]
        return results[0]["id"]
    return None


def get_existing_collection_ids() -> set[int]:
    """Get Discogs release IDs already in collection."""
    ids = set()
    page = 1

    while True:
        data = discogs_get(
            f"/users/{DISCOGS_USERNAME}/collection/folders/0/releases",
            {"per_page": 100, "page": page},
        )

        for item in data.get("releases", []):
            ids.add(item["id"])

        if page >= data["pagination"]["pages"]:
            break
        page += 1

    return ids


def add_to_collection(release_id: int) -> bool:
    """Add a release to Discogs collection. Returns True on success."""
    resp = discogs_post(
        f"/users/{DISCOGS_USERNAME}/collection/folders/0/releases/{release_id}"
    )
    return resp.status_code == 201


# --- State management ---
def load_state() -> dict:
    """Load previous sync state."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    """Save sync state."""
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# --- Main ---
def main():
    dry_run = "--apply" not in sys.argv
    force_resync = "--force" in sys.argv

    if dry_run:
        print("🔍 DRY RUN MODE (use --apply to actually add to Discogs)\n")
    else:
        print("🚀 APPLY MODE - will add releases to Discogs\n")

    # Load state
    state = load_state()

    # Step 1: Fetch MusicBrainz collection
    print("Step 1: Fetching MusicBrainz collection...")
    releases = get_collection_releases()
    print(f"  Found {len(releases)} releases\n")

    # Step 2: Check what's already in Discogs collection
    print("Step 2: Checking existing Discogs collection...")
    existing_ids = get_existing_collection_ids()
    print(f"  Already in collection: {len(existing_ids)} releases\n")

    # Step 3: Find Discogs IDs for each release
    print("Step 3: Finding Discogs releases...")

    for i, rel in enumerate(releases, 1):
        # Skip if already processed (unless force)
        if not force_resync and rel.mbid in state:
            saved = state[rel.mbid]
            rel.discogs_id = saved.get("discogs_id")
            rel.status = saved.get("status", "pending")
            rel.search_method = saved.get("search_method", "")
            continue

        print(f"  [{i}/{len(releases)}] {rel.display}", end="")

        # Method 1: Use existing Discogs URL
        if rel.discogs_url:
            match = re.search(r"/release/(\d+)", rel.discogs_url)
            if match:
                rel.discogs_id = int(match.group(1))
                rel.search_method = "url"
                print(f" → Discogs ID: {rel.discogs_id} (from MB link)")
            else:
                rel.status = "error"
                rel.error = "Invalid Discogs URL"
                print(" → ERROR: Invalid URL")
                continue

        # Method 2: Search by barcode
        if not rel.discogs_id and rel.barcode:
            rel.discogs_id = search_discogs_by_barcode(rel.barcode)
            if rel.discogs_id:
                rel.search_method = "barcode"
                print(f" → Discogs ID: {rel.discogs_id} (from barcode)")

        # Method 3: Search by artist + title
        if not rel.discogs_id:
            rel.discogs_id = search_discogs_by_query(rel.artist, rel.title)
            if rel.discogs_id:
                rel.search_method = "search"
                print(f" → Discogs ID: {rel.discogs_id} (from search)")

        if not rel.discogs_id:
            rel.status = "not_found"
            print(" → NOT FOUND on Discogs")

    print()

    # Step 4: Add to collection
    print("Step 4: Adding to Discogs collection...")

    to_add = []
    for rel in releases:
        if not rel.discogs_id:
            continue
        if rel.discogs_id in existing_ids:
            rel.status = "already_in_collection"
            continue
        if rel.status in ("added", "already_in_collection"):
            continue
        to_add.append(rel)

    if not to_add:
        print("  Nothing new to add!")
    else:
        for i, rel in enumerate(to_add, 1):
            if dry_run:
                rel.status = "would_add"
                print(f"  [{i}/{len(to_add)}] Would add: {rel.display} (Discogs {rel.discogs_id})")
            else:
                print(f"  [{i}/{len(to_add)}] Adding: {rel.display} (Discogs {rel.discogs_id})", end="")
                if add_to_collection(rel.discogs_id):
                    rel.status = "added"
                    print(" ✓")
                else:
                    rel.status = "error"
                    rel.error = "Failed to add"
                    print(" ✗")

    print()

    # Save state
    new_state = {}
    for rel in releases:
        new_state[rel.mbid] = {
            "title": rel.title,
            "artist": rel.artist,
            "discogs_id": rel.discogs_id,
            "status": rel.status,
            "search_method": rel.search_method,
            "error": rel.error,
        }
    save_state(new_state)

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    status_counts = {}
    for rel in releases:
        status_counts[rel.status] = status_counts.get(rel.status, 0) + 1

    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    if dry_run:
        print("\nRun with --apply to actually add releases to Discogs")
    print(f"\nState saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
