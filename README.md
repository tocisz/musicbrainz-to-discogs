# MusicBrainz ↔ Discogs Sync

Sync your MusicBrainz CD collection to Discogs and find missing cross-links between the two databases.

## Prerequisites

- Python 3.10+
- A [MusicBrainz](https://musicbrainz.org/) account with a public collection
- A [Discogs](https://www.discogs.com/) personal access token

## Setup

### 1. Create Discogs personal token

Go to https://www.discogs.com/settings/developers and generate a token.

### 2. Create `.env` file

```
DISCOGS_PERSONAL_TOKEN=your_token_here
```

### 3. Edit `settings.json`

```json
{
    "musicbrainz_collection_id": "your-collection-uuid"
}
```

### 4. Install dependencies

```bash
pip install requests python-dotenv
```

## Commands

### `check_links` — Check Discogs links

Shows which releases in your MusicBrainz collection already have Discogs URL relationships.

```bash
python cli.py check_links
```

Output:
```
WITH DISCOGS LINK (10/22)
  ✓ Coldplay - A Rush of Blood to the Head
    https://www.discogs.com/release/4436855 (ID: 4436855)

WITHOUT DISCOGS LINK (12/22)
  ✗ La Roux - La Roux (2009)
    MB: 07eb23a8-...  Barcode: 602527095288
```

### `propose` — Propose Discogs URLs to add

Searches Discogs for releases missing links and shows which URLs should be added to MusicBrainz.

```bash
python cli.py propose
```

Output:
```
PROPOSED CHANGES
  La Roux - La Roux
    MusicBrainz: https://musicbrainz.org/release/07eb23a8-...
    Discogs URL to add: https://www.discogs.com/release/1883981
```

### `sync` — Sync to Discogs collection

Adds releases from your MusicBrainz collection to your Discogs collection.

```bash
python cli.py sync            # Dry run (preview)
python cli.py sync --apply    # Actually add releases
python cli.py sync --apply --force   # Re-search all (ignore cache)
```

## How it works

### Finding Discogs releases

Each release is matched using three methods in order:

1. **Existing MusicBrainz link** — If the release already has a Discogs URL relationship, use it directly
2. **Barcode search** — Search Discogs by EAN/UPC barcode (most reliable)
3. **Text search** — Search by artist + title (fallback)

### State caching

Results are cached in `sync_state.json` to avoid re-searching on subsequent runs. Use `--force` to ignore the cache.

## File structure

```
├── cli.py              # Main entry point and commands
├── models.py           # Release dataclass
├── musicbrainz.py      # MusicBrainz API client
├── discogs.py          # Discogs API client
├── settings.json       # Configuration (gitignored)
├── .env                # API tokens (gitignored)
└── sync_state.json     # Cached search results (gitignored)
```

## API rate limits

- **MusicBrainz**: 1 request/second (enforced by the client)
- **Discogs**: 1 request/second (enforced by the client)
