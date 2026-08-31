"""
Parses a WhatsApp chat export (.txt) and extracts "lyrics entries":
each entry = one chat message that contains an attached image plus a
Spotify track link (on the same message / following continuation line).

Handles the quirks of real WhatsApp exports:
- Narrow no-break space (U+202F) or regular space between time and am/pm
- Invisible LTR/RTL marks (U+200E / U+200F) that WhatsApp sometimes prepends
- Multi-line messages (a caption/link on the line(s) after the header line
  belongs to the previous message, not a new one)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

# Strip invisible directional marks WhatsApp likes to sprinkle in
_INVISIBLE_CHARS = re.compile("[\u200e\u200f]")

# Header line, e.g.: 31/08/26, 12:40\u202fam - Harsh Shinde: hello
_HEADER_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s*"
    r"(?P<time>\d{1,2}:\d{2}(?:\s|\u202f|\u00a0)*[ap]\.?m\.?)"
    r"\s*-\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_SENDER_RE = re.compile(r"^(?P<sender>[^:]{1,60}?): (?P<msg>.*)$")

_IMAGE_RE = re.compile(
    r"([\w\-]+\.(?:jpg|jpeg|png|webp|gif))", re.IGNORECASE
)
_SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/track/([A-Za-z0-9]+)(?:\?[^\s]*)?"
)


@dataclass
class ChatMessage:
    timestamp: datetime
    sender: Optional[str]
    content: str


@dataclass
class LyricsEntry:
    timestamp: datetime
    sender: Optional[str]
    image_file: str
    spotify_track_id: str
    spotify_url: str
    raw_message: str
    in_range: bool = False


def _clean(line: str) -> str:
    return _INVISIBLE_CHARS.sub("", line).rstrip("\n")


def _parse_timestamp(date_str: str, time_str: str) -> Optional[datetime]:
    time_str = (
        time_str.replace("\u202f", " ")
        .replace("\u00a0", " ")
        .replace(".", "")
        .strip()
    )
    time_str = re.sub(r"\s+", " ", time_str)
    for date_fmt in ("%d/%m/%y", "%d/%m/%Y"):
        for time_fmt in ("%I:%M %p",):
            try:
                return datetime.strptime(f"{date_str} {time_str}", f"{date_fmt} {time_fmt}")
            except ValueError:
                continue
    return None


def parse_chat_file(path: str) -> List[ChatMessage]:
    """Parse the raw .txt export into a list of ChatMessage (multi-line
    continuations merged into the message they belong to)."""
    messages: List[ChatMessage] = []

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = _clean(raw_line)
            if not line.strip():
                continue

            m = _HEADER_RE.match(line)
            if m:
                ts = _parse_timestamp(m.group("date"), m.group("time"))
                rest = m.group("rest")
                sm = _SENDER_RE.match(rest)
                if sm:
                    sender, content = sm.group("sender"), sm.group("msg")
                else:
                    sender, content = None, rest
                if ts is not None:
                    messages.append(ChatMessage(timestamp=ts, sender=sender, content=content))
                    continue
                # If timestamp failed to parse, fall through and treat as continuation

            # Continuation line: append to the previous message
            if messages:
                messages[-1].content += "\n" + line

    return messages


def extract_lyrics_entries(messages: List[ChatMessage]) -> List[LyricsEntry]:
    """From parsed messages, pull out ones that reference both an image
    attachment and a Spotify track link."""
    entries: List[LyricsEntry] = []

    for msg in messages:
        img_match = _IMAGE_RE.search(msg.content)
        spotify_match = _SPOTIFY_RE.search(msg.content)
        if not img_match or not spotify_match:
            continue

        entries.append(
            LyricsEntry(
                timestamp=msg.timestamp,
                sender=msg.sender,
                image_file=img_match.group(1),
                spotify_track_id=spotify_match.group(1),
                spotify_url=f"https://open.spotify.com/track/{spotify_match.group(1)}",
                raw_message=msg.content,
            )
        )

    return entries


def load_lyrics_entries(chat_txt_path: str) -> List[LyricsEntry]:
    return extract_lyrics_entries(parse_chat_file(chat_txt_path))
