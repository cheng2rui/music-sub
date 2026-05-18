"""MusicBrainz scraper (international fallback)."""
import logging
from typing import Optional
import musicbrainzngs
from app.scrapers.base import BaseScraper, MusicMeta, parse_duration_seconds

logger = logging.getLogger(__name__)

musicbrainzngs.set_useragent("MusicSub", "0.1.0", "https://github.com/music-sub")


class MusicBrainzScraper(BaseScraper):
    """MusicBrainz metadata scraper."""

    name = "musicbrainz"

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        """Search MusicBrainz for metadata."""
        try:
            query = f'recording:"{title}"'
            if artist:
                query += f' AND artist:"{artist}"'
            result = musicbrainzngs.search_recordings(query=query, limit=5)
        except Exception as e:
            logger.error(f"[musicbrainz] Search failed: {e}")
            return []

        results = []
        for rec in result.get("recording-list", []):
            artists = rec.get("artist-credit", [])
            artist_name = ""
            if artists and isinstance(artists[0], dict):
                artist_name = artists[0].get("artist", {}).get("name", "")

            releases = rec.get("release-list", [])
            album_name = ""
            year = 0
            if releases:
                album_name = releases[0].get("title", "")
                date_str = releases[0].get("date", "")
                if date_str and len(date_str) >= 4:
                    try:
                        year = int(date_str[:4])
                    except ValueError:
                        pass

            results.append(MusicMeta(
                title=rec.get("title", ""),
                artist=artist_name,
                album=album_name,
                year=year,
                song_id=rec.get("id", ""),
                album_id=(releases[0].get("id", "") if releases else ""),
                duration=parse_duration_seconds(rec.get("length")),
                provider_extra={"recording_id": rec.get("id"), "release_id": releases[0].get("id", "") if releases else ""},
                source=self.name,
            ))
        return results

    def get_lyrics(self, song_id: str) -> str:
        """MusicBrainz doesn't provide lyrics."""
        return ""

    def get_cover(self, url: str) -> Optional[bytes]:
        """Download cover from Cover Art Archive."""
        if not url:
            return None
        import requests
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None
