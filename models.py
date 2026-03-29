"""Data models."""

import re
from dataclasses import dataclass, field


@dataclass
class Release:
    mbid: str
    title: str
    artist: str
    date: str = ""
    barcode: str = ""
    discogs_url: str | None = None
    discogs_id: int | None = None
    status: str = "pending"
    search_method: str = ""
    error: str = ""

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def discogs_id_from_url(self) -> int | None:
        """Extract Discogs release ID from URL."""
        if self.discogs_url:
            match = re.search(r"/release/(\d+)", self.discogs_url)
            return int(match.group(1)) if match else None
        return None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "artist": self.artist,
            "discogs_id": self.discogs_id,
            "status": self.status,
            "search_method": self.search_method,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, mbid: str, data: dict) -> "Release":
        return cls(
            mbid=mbid,
            title=data["title"],
            artist=data["artist"],
            discogs_id=data.get("discogs_id"),
            status=data.get("status", "pending"),
            search_method=data.get("search_method", ""),
            error=data.get("error", ""),
        )
