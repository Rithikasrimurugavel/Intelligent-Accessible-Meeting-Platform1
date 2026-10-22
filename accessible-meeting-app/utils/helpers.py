import base64
import html
import secrets
import string
from datetime import datetime
from typing import Optional


# No I / O / 0 / 1: they sound alike or look alike, which makes codes hard to speak and hear.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_meeting_code(prefix: str = "AM") -> str:
    """Generate a voice-friendly meeting code like AM-8F3K92."""
    alphabet = CODE_ALPHABET
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(6))


def format_timestamp(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now()).strftime("%H:%M:%S")


def audio_bytes_to_b64(audio_bytes: bytes) -> str:
    return base64.b64encode(audio_bytes).decode("utf-8")


def detect_audio_mime(data: bytes) -> str:
    """Sniff audio container so st.audio gets the right MIME type (HF gives WAV/FLAC, gTTS gives MP3)."""
    if data[:4] == b"RIFF":
        return "audio/wav"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if data[:4] == b"fLaC":
        return "audio/flac"
    if data[:4] == b"OggS":
        return "audio/ogg"
    return "audio/wav"


def esc(value) -> str:
    """HTML-escape any user-provided text before putting it into unsafe_allow_html markup."""
    return html.escape("" if value is None else str(value))


def html_block(markup: str) -> str:
    """Strip per-line indentation so Markdown never treats indented HTML as a code block."""
    return "".join(line.strip() for line in markup.splitlines())


def get_role_display_name(role: str) -> str:
    mapping = {
        "manager": "Meeting Host / Manager",
        "normal": "Normal Participant",
        "blind": "Visually Impaired / Blind",
        "deaf": "Deaf / Hearing Impaired",
        "mute": "Mute / Speech Impaired",
        "system": "System Notification",
    }
    return mapping.get((role or "").lower(), (role or "").title())


def get_role_icon(role: str) -> str:
    mapping = {"manager": "👑", "normal": "👤", "blind": "👁️", "deaf": "🧏‍♂️", "mute": "🖐️", "system": "📢"}
    return mapping.get((role or "").lower(), "👤")
