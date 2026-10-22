from typing import Optional

import streamlit as st


def render_audio_recorder(key: str = "meeting_audio_input") -> Optional[bytes]:
    """Render a voice recorder. Returns raw audio bytes (WAV) when a recording exists, else None."""
    st.markdown("### 🎤 Voice Recording Input")
    st.caption("Click the microphone, record your message, then click stop to transcribe and send.")

    if hasattr(st, "audio_input"):
        audio_value = st.audio_input("Record Voice Message", key=key)
        return audio_value.getvalue() if audio_value is not None else None

    uploaded = st.file_uploader("Upload audio recording (.wav / .mp3 / .ogg)",
                                type=["wav", "mp3", "ogg"], key=f"{key}_upload")
    return uploaded.getvalue() if uploaded is not None else None
