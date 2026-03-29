#!/usr/bin/env python3
"""MusicBrainz to Discogs sync tool."""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

SETTINGS_FILE = Path(__file__).parent / "settings.json"
STATE_FILE = Path(__file__).parent / "sync_state.json"


def load_settings() -> dict:
    return json.loads(SETTINGS_FILE.read_text())

from models import Release
from musicbrainz import MusicBrainzClient
from discogs import DiscogsClient


def get_clients(settings: dict) -> tuple[MusicBrainzClient, DiscogsClient]:
    """Initialize API clients from environment."""
    token = os.environ.get("DISCOGS_PERSONAL_TOKEN")
    if not token:
        print("Error: DISCOGS_PERSONAL_TOKEN not set in .env")
        sys.exit(1)

    identity = DiscogsClient(token, "").get_identity()
    mb = MusicBrainzClient(settings["musicbrainz_collection_id"])
    dg = DiscogsClient(token, identity["username"])

    return mb, dg


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(releases: list[Release]):
    state = {r.mbid: r.to_dict() for r in releases}
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# --- Commands ---

def cmd_check_links():
    """Check which releases have Discogs links and which don't."""
    settings = load_settings()
    mb = MusicBrainzClient(settings["musicbrainz_collection_id"])

    info = mb.get_collection_info()
    print(f"Collection: {info['name']} ({info['editor']}) - {info['release-count']} releases\n")

    releases = mb.get_collection_releases()

    with_link = [r for r in releases if r.discogs_url]
    without_link = [r for r in releases if not r.discogs_url]

    print("=" * 60)
    print(f"WITH DISCOGS LINK ({len(with_link)}/{len(releases)})")
    print("=" * 60)
    for r in with_link:
        print(f"  ✓ {r.display}")
        print(f"    {r.discogs_url} (ID: {r.discogs_id_from_url})")
        print()

    print("=" * 60)
    print(f"WITHOUT DISCOGS LINK ({len(without_link)}/{len(releases)})")
    print("=" * 60)
    for r in without_link:
        print(f"  ✗ {r.display} ({r.date})")
        print(f"    MB: {r.mbid}  Barcode: {r.barcode or 'N/A'}")
        print()

    print(f"Summary: {len(with_link)} linked, {len(without_link)} unlinked")


def cmd_propose():
    """Propose Discogs URLs for releases missing links."""
    settings = load_settings()
    mb, dg = get_clients(settings)

    info = mb.get_collection_info()
    print(f"Collection: {info['name']} - {info['release-count']} releases\n")

    releases = mb.get_collection_releases()
    without_link = [r for r in releases if not r.discogs_url]

    if not without_link:
        print("All releases already have Discogs links!")
        return

    print(f"Searching Discogs for {len(without_link)} releases without links...\n")

    results = []
    for i, rel in enumerate(without_link, 1):
        print(f"  [{i}/{len(without_link)}] {rel.display}", end="")

        discogs_id = None

        # Try barcode first
        if rel.barcode:
            discogs_id = dg.search_by_barcode(rel.barcode)

        # Try text search
        if not discogs_id:
            discogs_id = dg.search_by_query(rel.artist, rel.title)

        if discogs_id:
            results.append((rel, discogs_id))
            print(f" → found")
        else:
            print(" → NOT FOUND")

    print()
    print("=" * 70)
    print("PROPOSED CHANGES")
    print("=" * 70)
    print()

    for rel, discogs_id in results:
        mb_url = f"https://musicbrainz.org/release/{rel.mbid}"
        discogs_url = f"https://www.discogs.com/release/{discogs_id}"
        print(f"  {rel.display}")
        print(f"    MusicBrainz: {mb_url}")
        print(f"    Discogs URL to add: {discogs_url}")
        print()

    print(f"Found {len(results)}/{len(without_link)} Discogs matches")


def cmd_sync():
    """Sync MusicBrainz collection to Discogs."""
    dry_run = "--apply" not in sys.argv
    force = "--force" in sys.argv

    if dry_run:
        print("🔍 DRY RUN (use --apply to add to Discogs)\n")
    else:
        print("🚀 APPLY MODE\n")

    settings = load_settings()
    mb, dg = get_clients(settings)
    state = load_state()

    # Step 1: Fetch MB collection
    print("Step 1: Fetching MusicBrainz collection...")
    releases = mb.get_collection_releases()
    print(f"  {len(releases)} releases\n")

    # Step 2: Check existing Discogs collection
    print("Step 2: Checking existing Discogs collection...")
    existing_ids = set(dg.get_collection_releases())
    print(f"  {len(existing_ids)} already in collection\n")

    # Step 3: Find Discogs IDs
    print("Step 3: Finding Discogs releases...")
    for i, rel in enumerate(releases, 1):
        # Use cached state unless forced
        if not force and rel.mbid in state:
            saved = state[rel.mbid]
            rel.discogs_id = saved.get("discogs_id")
            rel.status = saved.get("status", "pending")
            rel.search_method = saved.get("search_method", "")
            continue

        print(f"  [{i}/{len(releases)}] {rel.display}", end="")

        # Method 1: MB link
        if rel.discogs_url:
            rel.discogs_id = rel.discogs_id_from_url
            rel.search_method = "url"
            print(f" → {rel.discogs_id} (MB link)")

        # Method 2: Barcode
        if not rel.discogs_id and rel.barcode:
            rel.discogs_id = dg.search_by_barcode(rel.barcode)
            if rel.discogs_id:
                rel.search_method = "barcode"
                print(f" → {rel.discogs_id} (barcode)")

        # Method 3: Text search
        if not rel.discogs_id:
            rel.discogs_id = dg.search_by_query(rel.artist, rel.title)
            if rel.discogs_id:
                rel.search_method = "search"
                print(f" → {rel.discogs_id} (search)")

        if not rel.discogs_id:
            rel.status = "not_found"
            print(" → NOT FOUND")

    print()

    # Step 4: Add to collection
    print("Step 4: Adding to Discogs...")
    to_add = [
        r for r in releases
        if r.discogs_id and r.discogs_id not in existing_ids
        and r.status not in ("added", "already_in_collection")
    ]

    if not to_add:
        print("  Nothing to add!")
    else:
        for i, rel in enumerate(to_add, 1):
            if dry_run:
                rel.status = "would_add"
                print(f"  [{i}/{len(to_add)}] Would add: {rel.display} ({rel.discogs_id})")
            else:
                print(f"  [{i}/{len(to_add)}] Adding: {rel.display} ({rel.discogs_id})", end="")
                if dg.add_to_collection(rel.discogs_id):
                    rel.status = "added"
                    print(" ✓")
                else:
                    rel.status = "error"
                    rel.error = "Failed to add"
                    print(" ✗")

    # Mark already-in-collection
    for r in releases:
        if r.discogs_id and r.discogs_id in existing_ids:
            r.status = "already_in_collection"

    save_state(releases)

    # Summary
    print("\n" + "=" * 40)
    counts = {}
    for r in releases:
        counts[r.status] = counts.get(r.status, 0) + 1
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")

    if dry_run:
        print("\nRun with --apply to add releases")


# --- Main ---

COMMANDS = {
    "check_links": cmd_check_links,
    "propose": cmd_propose,
    "sync": cmd_sync,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python cli.py <command> [options]")
        print()
        print("Commands:")
        print("  check_links    Check which releases have Discogs links")
        print("  propose        Propose Discogs URLs for releases missing links")
        print("  sync           Sync collection to Discogs")
        print()
        print("Sync options:")
        print("  --apply        Actually add to Discogs (default: dry run)")
        print("  --force        Re-search even if cached")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
