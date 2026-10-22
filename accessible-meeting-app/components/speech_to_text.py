import hashlib

import streamlit as st

from components.audio_recorder import render_audio_recorder
from services.message_service import message_service


def render_speech_to_text_widget(meeting_id: str, user_id: str, user_name: str, user_role: str,
                                 key: str = "stt_audio_widget"):
    """Record -> transcribe -> post. Each distinct recording is processed exactly once."""
    audio_bytes = render_audio_recorder(key=key)
    if not audio_bytes:
        return

    digest = hashlib.md5(audio_bytes).hexdigest()
    state_key = f"_last_audio_{key}"
    if st.session_state.get(state_key) == digest:
        return  # already processed (prevents duplicate messages after st.rerun)
    st.session_state[state_key] = digest

    with st.spinner("⌛ Transcribing speech..."):
        success, _msg, status_text = message_service.process_and_send_voice_message(
            meeting_id=meeting_id, sender_id=user_id, sender_name=user_name,
            sender_role=user_role, audio_bytes=audio_bytes)

    if success:
        st.rerun()
    else:
        st.error(f"❌ {status_text}")
