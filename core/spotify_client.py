"""
Thin wrapper around Spotify's Web API (client-credentials flow — no user
login needed, just a Client ID + Secret from https://developer.spotify.com).

Note: Spotify's track object has no "genre" field. Genre lives on the
ARTIST, so we fetch the primary artist and pull their genre list.
"""

import base64
import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"


@dataclass
class SongMetadata:
    track_id: str
    title: str
    artists: List[str]
    primary_artist_id: str
    album: str
    release_date: str
    cover_url: str
    spotify_url: str
    duration_ms: int
    genres: List[str] = field(default_factory=list)

    @property
    def genre(self) -> str:
        return self.genres[0].title() if self.genres else "Unsorted"

    @property
    def artist_display(self) -> str:
        return ", ".join(self.artists)


class SpotifyAuthError(Exception):
    pass


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._artist_genre_cache = {}

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {auth_header}"},
            timeout=15,
        )
        if resp.status_code != 200:
            raise SpotifyAuthError(
                f"Spotify auth failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def _get(self, path: str) -> dict:
        headers = {"Authorization": f"Bearer {self._get_token()}"}
        resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=15)
        if resp.status_code == 401:
            # token might've just expired server-side; refresh once and retry
            self._token = None
            headers = {"Authorization": f"Bearer {self._get_token()}"}
            resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _artist_genres(self, artist_id: str) -> List[str]:
        if artist_id in self._artist_genre_cache:
            return self._artist_genre_cache[artist_id]
        data = self._get(f"/artists/{artist_id}")
        genres = data.get("genres", []) or []
        self._artist_genre_cache[artist_id] = genres
        return genres

    def get_track(self, track_id: str) -> SongMetadata:
        data = self._get(f"/tracks/{track_id}")

        artists = data.get("artists", [])
        artist_names = [a["name"] for a in artists]
        primary_artist_id = artists[0]["id"] if artists else ""

        genres: List[str] = []
        if primary_artist_id:
            try:
                genres = self._artist_genres(primary_artist_id)
            except requests.HTTPError:
                genres = []

        images = data.get("album", {}).get("images", [])
        cover_url = images[0]["url"] if images else ""

        return SongMetadata(
            track_id=data["id"],
            title=data.get("name", "Unknown Title"),
            artists=artist_names,
            primary_artist_id=primary_artist_id,
            album=data.get("album", {}).get("name", ""),
            release_date=data.get("album", {}).get("release_date", ""),
            cover_url=cover_url,
            spotify_url=data.get("external_urls", {}).get("spotify", ""),
            duration_ms=data.get("duration_ms", 0),
            genres=genres,
        )
