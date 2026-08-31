"""
Organizes songs into an Obsidian-friendly vault:

Vault/
  Genres/
    <Genre>/
      <Title> - <Artist>.md      # song note, YAML frontmatter + ![[image]]
      attachments/
        <original lyric image>
    <Genre>.md                    # hub note for the genre (graph node)
  Artists/
    <Artist>.md                   # hub note per artist (graph node)
  Albums/
    <Album>.md                    # hub note per album (graph node)

Each song note embeds the lyric image (![[file.jpg]]) and links out to
its artist(s), album, and genre via [[wikilinks]]. Obsidian's Graph View
draws an edge for every wikilink, so songs sharing an artist or album end
up visibly clustered together — the hub notes exist so those nodes show
up even before/without a "real" article written about that artist/album.
"""

import re
import shutil
from pathlib import Path
from typing import List

from .spotify_client import SongMetadata

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize(name: str, max_len: int = 120) -> str:
    name = _ILLEGAL_CHARS.sub("-", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:max_len].rstrip(" .") or "untitled"


def genre_folder_name(genre: str) -> str:
    return sanitize(genre) or "Unsorted"


class VaultManager:
    def __init__(self, vault_root: str):
        self.root = Path(vault_root)
        self.genres_dir = self.root / "Genres"
        self.artists_dir = self.root / "Artists"
        self.albums_dir = self.root / "Albums"
        for d in (self.genres_dir, self.artists_dir, self.albums_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- paths --
    def genre_dir(self, genre: str) -> Path:
        d = self.genres_dir / genre_folder_name(genre)
        (d / "attachments").mkdir(parents=True, exist_ok=True)
        return d

    def note_path(self, genre: str, meta: SongMetadata) -> Path:
        stem = sanitize(f"{meta.title} - {meta.artist_display}")
        return self.genre_dir(genre) / f"{stem}.md"

    # ---------------------------------------------------- hub / stub notes
    def ensure_hub_note(self, folder: Path, name: str, kind: str) -> Path:
        """Creates a minimal note for an artist/album/genre if one doesn't
        already exist, so it shows up as a real node in Obsidian's Graph
        View (not just an unresolved-link ghost)."""
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{sanitize(name)}.md"
        if not path.exists():
            content = (
                "---\n"
                f'title: "{name}"\n'
                f'type: "{kind}"\n'
                "---\n\n"
                f"# {name}\n"
            )
            path.write_text(content, encoding="utf-8")
        return path

    def ensure_artist_note(self, artist: str) -> Path:
        return self.ensure_hub_note(self.artists_dir, artist, "artist")

    def ensure_album_note(self, album: str) -> Path:
        return self.ensure_hub_note(self.albums_dir, album, "album")

    def ensure_genre_note(self, genre: str) -> Path:
        return self.ensure_hub_note(self.genres_dir, genre, "genre")

    # ------------------------------------------------------------- notes --
    def build_note(self, meta: SongMetadata, artists: List[str], genre: str,
                    image_filename: str, date_added: str) -> str:
        artist_links = ", ".join(f"[[{a}]]" for a in artists) if artists else ""
        tags = ["lyrics", genre_folder_name(genre).lower().replace(" ", "-")]
        frontmatter = "\n".join(
            [
                "---",
                f'title: "{meta.title}"',
                f'artist: "{meta.artist_display}"',
                f'album: "{meta.album}"',
                f'genre: "{meta.genre}"',
                f"genres_all: {meta.genres!r}",
                f'release_date: "{meta.release_date}"',
                f'spotify_url: "{meta.spotify_url}"',
                f'date_added: "{date_added}"',
                f"tags: [{', '.join(tags)}]",
                "---",
            ]
        )
        body = (
            f"\n# {meta.title}\n\n"
            f"**Artist:** {artist_links}  \n"
            f"**Album:** [[{meta.album}]]  \n"
            f"**Genre:** [[{genre}]]  \n"
            f"**Added:** {date_added}\n\n"
            f"![[{image_filename}]]\n\n"
            f"[Listen on Spotify]({meta.spotify_url})\n"
        )
        return frontmatter + body

    def add_song(self, meta: SongMetadata, artists: List[str], genre: str,
                 source_image_path: Path, date_added: str, move: bool = True) -> dict:
        """Writes the note + copies/moves the image into the vault, and
        makes sure the artist/album/genre hub notes exist so Graph View
        links resolve. Returns a dict describing where things ended up
        (for the JSON store)."""
        gdir = self.genre_dir(genre)
        dest_image = gdir / "attachments" / source_image_path.name

        # Avoid clobbering an existing file with the same name
        counter = 1
        while dest_image.exists():
            dest_image = gdir / "attachments" / (
                f"{source_image_path.stem}_{counter}{source_image_path.suffix}"
            )
            counter += 1

        if move:
            shutil.move(str(source_image_path), str(dest_image))
        else:
            shutil.copy2(str(source_image_path), str(dest_image))

        # Hub notes for graph nodes (created once, reused after that)
        for a in artists:
            self.ensure_artist_note(a)
        if meta.album:
            self.ensure_album_note(meta.album)
        self.ensure_genre_note(genre)

        note_content = self.build_note(meta, artists, genre, dest_image.name, date_added)
        note_file = self.note_path(genre, meta)
        counter = 1
        while note_file.exists():
            note_file = self.genre_dir(genre) / (
                f"{sanitize(f'{meta.title} - {meta.artist_display}')}_{counter}.md"
            )
            counter += 1
        note_file.write_text(note_content, encoding="utf-8")

        return {
            "note_path": str(note_file.relative_to(self.root)),
            "image_path": str(dest_image.relative_to(self.root)),
        }
