"""
Lyrics -> Spotify -> Obsidian Vault organizer.

Run with:  streamlit run app.py

Workflow:
1. Point it at your WhatsApp chat .txt export (browse/upload it, or set a
   path) + the folder containing the exported media (images).
2. Pick a date range (or "up to today").
3. Scan -> review the matched image+Spotify-link pairs.
4. Fetch Spotify metadata, review/edit the auto-detected genre per song.
5. Organize -> writes an Obsidian vault (Genres/<Genre>/*.md + attachments,
   plus Artists/ and Albums/ hub notes) with [[wikilinks]] connecting each
   song to its artist(s)/album/genre for Obsidian's Graph View, and
   mirrors everything into JSON (with the same relations pre-computed)
   for a future web UI.
6. Optionally delete the lyric images that fall OUTSIDE the chosen range.

Everything runs locally. Nothing leaves your machine except calls to the
Spotify Web API to fetch public track/artist metadata.

Config: any of the fields below can be pre-filled via a `.env` file (see
.env.example) so you don't have to retype paths/keys every run. Values
typed into the sidebar always override the .env defaults for that run.
"""

import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()  # populates os.environ from a local .env file, if present
except ImportError:
    pass

from core.whatsapp_parser import load_lyrics_entries
from core.spotify_client import SpotifyClient, SpotifyAuthError
from core.vault_manager import VaultManager
from core.json_store import JsonStore

st.set_page_config(page_title="Lyrics Vault Organizer", page_icon="🎵", layout="wide")

# ---------------------------------------------------------------- state ----
for key, default in [
    ("entries", None),          # list[LyricsEntry] from the chat file
    ("metadata_df", None),      # editable dataframe with fetched Spotify info
    ("processed", False),
    ("resolved_chat_path", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title("🎵 Lyrics Vault Organizer")
st.caption(
    "Turns WhatsApp lyric screenshots + Spotify links into an Obsidian vault, "
    "sorted by genre and cross-linked by artist/album, with a JSON mirror for later use."
)

# --------------------------------------------------------------- sidebar ----
with st.sidebar:
    if Path(".env").exists():
        st.caption("✅ Loaded defaults from .env — override anything below as needed.")
    else:
        st.caption("💡 Tip: copy `.env.example` to `.env` to stop retyping these.")

    st.header("1. Chat export")
    chat_source = st.radio(
        "Chat file", ["Browse / upload", "Type a path"], horizontal=True,
        label_visibility="collapsed",
    )
    if chat_source == "Browse / upload":
        uploaded_chat = st.file_uploader("WhatsApp chat export (.txt)", type=["txt"])
        if uploaded_chat is not None:
            tmp_path = Path(tempfile.gettempdir()) / f"lvo_{uploaded_chat.name}"
            tmp_path.write_bytes(uploaded_chat.getvalue())
            st.session_state.resolved_chat_path = str(tmp_path)
            st.caption(f"Using uploaded file: {uploaded_chat.name}")
        chat_txt_path = st.session_state.resolved_chat_path
    else:
        chat_txt_path = st.text_input(
            "WhatsApp chat export (.txt) path",
            value=os.environ.get("CHAT_TXT_PATH", ""),
        )
        st.session_state.resolved_chat_path = chat_txt_path

    media_folder = st.text_input(
        "Folder containing the exported images",
        value=os.environ.get("MEDIA_FOLDER", ""),
        help="The folder WhatsApp exported the media into (usually the same "
        "folder as the chat .txt, or wherever you extracted the export zip).",
    )

    st.header("2. Spotify API")
    client_id = st.text_input(
        "Client ID", value=os.environ.get("SPOTIFY_CLIENT_ID", ""), type="password"
    )
    client_secret = st.text_input(
        "Client Secret", value=os.environ.get("SPOTIFY_CLIENT_SECRET", ""), type="password"
    )
    st.caption("Get these free at developer.spotify.com/dashboard")

    st.header("3. Output location")
    vault_root = st.text_input("Obsidian vault folder", value=os.environ.get("VAULT_ROOT", "./LyricsVault"))
    data_root = st.text_input("JSON data folder", value=os.environ.get("DATA_ROOT", "./LyricsVaultData"))

    st.header("4. Date range")
    start_date = st.date_input("From date", value=date(2020, 1, 1))
    up_to_today = st.checkbox("Up to today", value=True)
    if up_to_today:
        end_date = date.today()
        st.caption(f"Until: **{end_date.isoformat()}** (today)")
    else:
        end_date = st.date_input("To date", value=date.today())

# ------------------------------------------------------------- step one ----
st.subheader("Step 1 — Scan the chat export")

if st.button("🔍 Scan chat file", type="primary"):
    if not chat_txt_path or not Path(chat_txt_path).exists():
        st.error("No chat file selected — browse/upload one or enter a valid path in the sidebar.")
    else:
        entries = load_lyrics_entries(chat_txt_path)
        st.session_state.entries = entries
        st.session_state.metadata_df = None
        st.session_state.processed = False
        st.success(f"Found {len(entries)} image+Spotify-link pairs in the chat.")

entries = st.session_state.entries
if entries:
    for e in entries:
        e.in_range = start_date <= e.timestamp.date() <= end_date

    df = pd.DataFrame(
        [
            {
                "Date": e.timestamp.strftime("%Y-%m-%d %H:%M"),
                "Image": e.image_file,
                "Spotify URL": e.spotify_url,
                "In range": e.in_range,
            }
            for e in entries
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    in_range = [e for e in entries if e.in_range]
    out_range = [e for e in entries if not e.in_range]
    c1, c2 = st.columns(2)
    c1.metric("In selected range (will be organized)", len(in_range))
    c2.metric("Outside range (eligible for deletion)", len(out_range))

    # ---------------------------------------------------------- step two ----
    st.subheader("Step 2 — Fetch Spotify metadata & review genres")

    if st.button("🎧 Fetch metadata for in-range songs"):
        if not client_id or not client_secret:
            st.error("Enter your Spotify Client ID and Secret in the sidebar first.")
        elif not in_range:
            st.warning("No entries in the selected date range.")
        else:
            try:
                sp = SpotifyClient(client_id, client_secret)
            except Exception as ex:
                st.error(f"Could not init Spotify client: {ex}")
                sp = None

            if sp:
                rows = []
                progress = st.progress(0.0, text="Fetching...")
                errors = []
                for i, e in enumerate(in_range):
                    try:
                        meta = sp.get_track(e.spotify_track_id)
                        rows.append(
                            {
                                "Date": e.timestamp.strftime("%Y-%m-%d %H:%M"),
                                "Image": e.image_file,
                                "Track ID": e.spotify_track_id,
                                "Title": meta.title,
                                "Artist": meta.artist_display,
                                "Album": meta.album,
                                "Genre": meta.genre,
                                "Detected genres": ", ".join(meta.genres),
                                "Spotify URL": e.spotify_url,
                                "Cover": meta.cover_url,
                                "Release date": meta.release_date,
                            }
                        )
                    except SpotifyAuthError as ex:
                        st.error(str(ex))
                        break
                    except Exception as ex:
                        errors.append(f"{e.image_file}: {ex}")
                    progress.progress((i + 1) / len(in_range))

                if rows:
                    st.session_state.metadata_df = pd.DataFrame(rows)
                    st.success(f"Fetched metadata for {len(rows)} song(s).")
                if errors:
                    st.warning("Some tracks failed to fetch:\n" + "\n".join(errors))

    if st.session_state.metadata_df is not None:
        st.write("Edit the **Genre** column below if you want to override Spotify's guess "
                 "before organizing — this decides the vault folder. Artist(s) and Album "
                 "are used to cross-link songs in Obsidian's Graph View and in the JSON.")
        edited_df = st.data_editor(
            st.session_state.metadata_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Cover": st.column_config.ImageColumn("Cover", width="small"),
            },
            disabled=[c for c in st.session_state.metadata_df.columns if c != "Genre"],
            key="metadata_editor",
        )
        st.session_state.metadata_df = edited_df

        # ------------------------------------------------------- step three
        st.subheader("Step 3 — Organize into the vault")
        if st.button("📁 Organize songs into vault", type="primary"):
            if not media_folder or not Path(media_folder).is_dir():
                st.error("Set a valid media folder path in the sidebar.")
            else:
                vault = VaultManager(vault_root)
                store = JsonStore(data_root)
                log = []
                progress = st.progress(0.0, text="Organizing...")
                rows = edited_df.to_dict("records")
                for i, row in enumerate(rows):
                    img_path = Path(media_folder) / row["Image"]
                    if not img_path.exists():
                        log.append(f"⚠️ Missing image, skipped: {row['Image']}")
                        progress.progress((i + 1) / len(rows))
                        continue

                    artist_list = [a.strip() for a in row["Artist"].split(",") if a.strip()]
                    genres_all = [g.strip() for g in row["Detected genres"].split(",") if g.strip()]

                    class _M:
                        pass
                    meta = _M()
                    meta.title = row["Title"]
                    meta.artist_display = row["Artist"]
                    meta.album = row["Album"]
                    meta.genre = row["Genre"]
                    meta.genres = genres_all
                    meta.release_date = row["Release date"]
                    meta.spotify_url = row["Spotify URL"]

                    date_added = row["Date"].split(" ")[0]
                    result = vault.add_song(
                        meta, artist_list, row["Genre"], img_path, date_added, move=True
                    )
                    record = {
                        "track_id": row["Track ID"],
                        "title": row["Title"],
                        "artist": row["Artist"],
                        "artists": artist_list,
                        "album": row["Album"],
                        "genre": row["Genre"],
                        "genres_all": genres_all,
                        "release_date": row["Release date"],
                        "spotify_url": row["Spotify URL"],
                        "date_added": date_added,
                        **result,
                    }
                    store.upsert_song(row["Track ID"], record)
                    log.append(f"✅ {row['Title']} — {row['Artist']} → {row['Genre']}")
                    progress.progress((i + 1) / len(rows))

                st.session_state.processed = True
                st.success("Done organizing!")
                st.code("\n".join(log))

# ------------------------------------------------------------- step four ----
st.subheader("Step 4 — Clean up images outside the date range")

if entries:
    out_range = [e for e in entries if not e.in_range]
    if out_range:
        with st.expander(f"⚠️ {len(out_range)} image(s) outside {start_date} → {end_date}", expanded=False):
            st.dataframe(
                pd.DataFrame(
                    [{"Date": e.timestamp.strftime("%Y-%m-%d %H:%M"), "Image": e.image_file} for e in out_range]
                ),
                use_container_width=True,
                hide_index=True,
            )
            confirm = st.checkbox(
                "I understand this permanently deletes these image files from the media folder."
            )
            if st.button("🗑️ Delete out-of-range images", disabled=not confirm):
                if not media_folder or not Path(media_folder).is_dir():
                    st.error("Set a valid media folder path in the sidebar.")
                else:
                    deleted, missing = [], []
                    for e in out_range:
                        p = Path(media_folder) / e.image_file
                        if p.exists():
                            p.unlink()
                            deleted.append(e.image_file)
                        else:
                            missing.append(e.image_file)
                    st.success(f"Deleted {len(deleted)} image(s).")
                    if missing:
                        st.info(f"{len(missing)} were already missing: {', '.join(missing)}")
    else:
        st.caption("Nothing outside the selected range.")
