# Lyrics Vault Organizer

Turns your "screenshot the lyrics + paste the Spotify link" WhatsApp habit
into an Obsidian vault, sorted by genre, with a JSON mirror for a future
web UI. Runs entirely locally — the only network calls go to Spotify's
Web API to fetch public track/artist metadata.

## Setup

```bash
cd lyrics_organizer
pip install -r requirements.txt
```

Get a free Spotify Client ID + Secret:
1. Go to https://developer.spotify.com/dashboard
2. Create an app (redirect URI doesn't matter here — set anything, e.g. `http://localhost:8501`)
3. Copy the **Client ID** and **Client Secret**

### Config via .env (recommended)

Copy `.env.example` to `.env` and fill in whatever you don't want to retype
each run:

```bash
cp .env.example .env
```

```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
CHAT_TXT_PATH=
MEDIA_FOLDER=
VAULT_ROOT=./LyricsVault
DATA_ROOT=./LyricsVaultData
```

The app auto-loads `.env` on startup and pre-fills the sidebar from it —
anything you leave blank just falls back to typing it in the app. Values
you edit in the sidebar for a given run always take priority over `.env`.

## Exporting the WhatsApp chat

In WhatsApp: open the chat → ⋮ menu → More → Export chat → **Include media**.
This gives you a `.txt` file plus a folder/zip of the attached images. Unzip
it somewhere and note the folder path — you'll enter both paths in the app.

## Running

```bash
streamlit run app.py
```

Then in the browser tab that opens:

1. **Sidebar** — pick the chat file via **Browse / upload** (a normal
   file picker) or switch to **Type a path** if you'd rather point at a
   path directly; set the media folder path, your Spotify credentials,
   where you want the vault + JSON data written, and the date range (or
   tick "Up to today"). Any of these pre-fill from `.env` if you set one up.
2. **Step 1 — Scan** — parses the chat, matches each image to the Spotify
   link that was sent with it, and flags which are inside/outside your
   date range.
3. **Step 2 — Fetch metadata** — pulls title/artist/album/genre from
   Spotify for everything in range. You can edit the **Genre** column
   before organizing — that's what decides the vault folder.
4. **Step 3 — Organize** — writes the vault:
   ```
   LyricsVault/
     Genres/
       Pop.md                    # hub note (graph node) for the genre
       Pop/
         Song Title - Artist.md
         attachments/
           IMG-....jpg
       Hip Hop.md
       Hip Hop/
         ...
     Artists/
       The Band.md                # hub note per artist
     Albums/
       Album Title.md              # hub note per album
   ```
   Each song note has YAML frontmatter (title, artist, genre, spotify_url,
   date_added, etc.), an `![[image]]` embed, and **`[[wikilinks]]`** to its
   artist(s), album, and genre. Open `LyricsVault` as an Obsidian vault and
   its **Graph View** will cluster songs that share an artist or album —
   the `Artists/` and `Albums/` hub notes exist so those nodes show up
   even before you've written anything about that artist/album yourself.

   Alongside it, `LyricsVaultData/` gets:
   ```
   songs.json             # master DB keyed by Spotify track id.
                           # each record includes related_by_artist /
                           # related_by_album — lists of other track ids —
                           # so a future web UI can draw the same graph
                           # without re-deriving it.
   genres/Pop.json         # per-genre list, mirrors the vault folders
   artists/The Band.json   # per-artist list
   albums/Album Title.json # per-album list
   ```
   Load `songs.json` (or a specific genre/artist/album file) from a future
   web app — no need to touch the vault or Spotify again.

5. **Step 4 — Clean up** — lists every image whose message falls
   *outside* the chosen date range and lets you delete them from the
   media folder after an explicit confirmation checkbox. Images that get
   organized in Step 3 are **moved** (not copied) out of the media
   folder into the vault, so by the end the media folder only contains
   whatever you chose not to process.

## Notes / limitations

- Spotify genres are attached to the *artist*, not the track, and many
  artists have no genres tagged at all — those fall back to `Unsorted`.
  Use the editable Genre column in Step 2 to fix these before organizing.
- Re-running Step 3 on the same tracks updates `songs.json` in place
  (keyed by track id) rather than duplicating entries, but it will
  create a new note/attachment copy if you run it twice on the same
  image without re-scanning — re-scan between runs to avoid that.
- Filenames are sanitized for illegal characters; duplicate note/image
  names get a numeric suffix instead of overwriting each other.
