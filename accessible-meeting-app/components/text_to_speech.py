import streamlit as st

from services.huggingface_service import huggingface_service
from utils.helpers import detect_audio_mime, esc


def render_tts_player(text: str, auto_play: bool = False, key: str = "tts_player"):
    """Text-to-Speech player (Hugging Face TTS, gTTS fallback). Generated audio is cached per text."""
    if not text or not text.strip():
        return

    cache_key = f"_tts_{key}"
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"**🔊 Audio Readout:** *\"{esc(text)}\"*")
    with col2:
        clicked = st.button("▶️ Read Aloud", key=f"btn_play_{key}")

    just_generated = False
    if clicked:
        with st.spinner("Generating speech..."):
            ok, audio, note = huggingface_service.text_to_speech(text)
        st.session_state[cache_key] = {"text": text, "ok": ok, "audio": audio, "note": note}
        just_generated = True

    cached = st.session_state.get(cache_key)
    if cached and cached["text"] == text:
        if cached["ok"] and cached["audio"]:
            st.audio(cached["audio"], format=detect_audio_mime(cached["audio"]),
                     autoplay=bool(auto_play and just_generated))
            st.caption(f"ℹ️ {cached['note']}")
        else:
            st.error(f"TTS Error: {cached['note']}")
