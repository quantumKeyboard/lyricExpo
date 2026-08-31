"""
Keeps a JSON mirror of the vault so a future web UI can load data without
touching the filesystem/Obsidian at all — including the same "songs that
share an artist or album are connected" relationships the vault expresses
via [[wikilinks]] and Graph View.

data/
  songs.json            # master DB, keyed by spotify track_id.
                         # each record also carries related_by_artist /
                         # related_by_album: lists of other track_ids,
                         # so a web UI can draw the same graph without
                         # re-deriving it.
  genres/<Genre>.json    # songs in that genre
  artists/<Artist>.json  # songs by that artist
  albums/<Album>.json    # songs in that album
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict

from .vault_manager import genre_folder_name, sanitize


class JsonStore:
    def __init__(self, data_root: str):
        self.root = Path(data_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.genres_dir = self.root / "genres"
        self.artists_dir = self.root / "artists"
        self.albums_dir = self.root / "albums"
        for d in (self.genres_dir, self.artists_dir, self.albums_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.master_path = self.root / "songs.json"
        self._db: Dict[str, dict] = self._load_master()

    def _load_master(self) -> Dict[str, dict]:
        if self.master_path.exists():
            try:
                return json.loads(self.master_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def has_track(self, track_id: str) -> bool:
        return track_id in self._db

    def upsert_song(self, track_id: str, record: dict) -> None:
        """record must include: genre (str), artists (list[str]), album (str)."""
        record.setdefault("artists", [])
        self._db[track_id] = record
        self._recompute_relations()
        self._save_master()
        self._rewrite_all_indexes()

    # ---------------------------------------------------------- internals
    def _recompute_relations(self) -> None:
        by_artist = defaultdict(list)
        by_album = defaultdict(list)
        for tid, rec in self._db.items():
            for a in rec.get("artists", []):
                by_artist[a].append(tid)
            if rec.get("album"):
                by_album[rec["album"]].append(tid)

        for tid, rec in self._db.items():
            related_artist = set()
            for a in rec.get("artists", []):
                related_artist.update(by_artist[a])
            related_artist.discard(tid)

            related_album = set(by_album.get(rec.get("album"), []))
            related_album.discard(tid)

            rec["related_by_artist"] = sorted(related_artist)
            rec["related_by_album"] = sorted(related_album)

    def _save_master(self) -> None:
        self.master_path.write_text(
            json.dumps(self._db, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _rewrite_all_indexes(self) -> None:
        genres = defaultdict(list)
        artists = defaultdict(list)
        albums = defaultdict(list)

        for rec in self._db.values():
            if rec.get("genre"):
                genres[rec["genre"]].append(rec)
            for a in rec.get("artists", []):
                artists[a].append(rec)
            if rec.get("album"):
                albums[rec["album"]].append(rec)

        for genre, songs in genres.items():
            path = self.genres_dir / f"{genre_folder_name(genre)}.json"
            path.write_text(json.dumps(songs, indent=2, ensure_ascii=False), encoding="utf-8")

        for artist, songs in artists.items():
            path = self.artists_dir / f"{sanitize(artist)}.json"
            path.write_text(json.dumps(songs, indent=2, ensure_ascii=False), encoding="utf-8")

        for album, songs in albums.items():
            path = self.albums_dir / f"{sanitize(album)}.json"
            path.write_text(json.dumps(songs, indent=2, ensure_ascii=False), encoding="utf-8")

    def all_songs(self):
        return list(self._db.values())
