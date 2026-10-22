"""
Sign-language input for mute / speech-impaired users, now part of the live video meeting.

The user's camera is the same one everybody sees. Hand tracking runs inside the user's own browser on that live video,
words appear in real time and are shown as subtitles on top of the video for the whole meeting. Every finished
sentence is also saved to the meeting conversation (automatically, or after the person edits it when auto-send is off).
"""
import streamlit as st

from components.video_call import render_video_call
from services.message_service import message_service
from services.sign_sentence import format_sentence

_MAX_WORDS = 40


def _send_sentence(text: str, confidence: float, meeting_id: str, user_id: str, user_name: str, user_role: str):
    ok, _m, status = message_service.process_and_send_sign_message(
        meeting_id=meeting_id, sender_id=user_id, sender_name=user_name, sender_role=user_role,
        detected_sign=text, confidence=confidence)
    log = st.session_state.setdefault("_sign_log", [])
    log.append(("✅ " if ok else "❌ ") + (text if ok else status))
    del log[:-5]
    return ok


def _set_pending(text: str, conf: float):
    st.session_state["_sign_pending_edit"] = text
    st.session_state["_sign_pending_conf"] = conf
    st.session_state["_sign_has_pending"] = True


def _send_pending_cb(ctx: tuple):
    """Button callback (runs before the rerun, so it may change the text box's state)."""
    text = (st.session_state.get("_sign_pending_edit") or "").strip()
    if text and _send_sentence(text, st.session_state.get("_sign_pending_conf", 0.9), *ctx):
        st.session_state["_sign_has_pending"] = False
        st.session_state["_sign_pending_edit"] = ""


def handle_sign_sentence(ev: dict, ctx: tuple):
    """A finished signed sentence from the browser: {"words": [...], "conf": float}."""
    words = [str(w).strip().lower()[:40] for w in (ev.get("words") or []) if str(w).strip()][:_MAX_WORDS]
    if not words:
        return
    text = format_sentence(words)
    try:
        conf = min(1.0, max(0.0, float(ev.get("conf", 0.85))))
    except (TypeError, ValueError):
        conf = 0.85
    if st.session_state.get("_sign_auto_send", True):
        _send_sentence(text, conf, *ctx)
    else:
        _set_pending(text, conf)


@st.fragment(run_every=2)
def _sign_log_fragment(ctx: tuple):
    # Manual review (auto-send off)
    if not st.session_state.get("_sign_auto_send", True) and st.session_state.get("_sign_has_pending"):
        st.text_input("✏️ Check / edit your sentence, then send", key="_sign_pending_edit")
        st.button("✉️ Send this sentence", key="sign_btn_send_pending", type="primary",
                  on_click=_send_pending_cb, args=(ctx,))
    for line in st.session_state.get("_sign_log", [])[::-1]:
        st.write(line)


def render_sign_language_component(meeting_id: str, user_id: str, user_name: str, user_role: str):
    """Live video + sign-language subtitles for the whole meeting."""
    st.markdown("### 🖐️ Live Video with Sign-Language Subtitles")
    st.info("📷 **Privacy:** your signs are read inside your own browser. Everyone in the meeting sees your video "
            "(like any video call) and the subtitles of what you sign. You can stop your video at any time.")

    st.session_state.setdefault("_sign_auto_send", True)
    st.toggle("Also save each finished sentence to the meeting chat automatically", key="_sign_auto_send")
    with st.expander("How it works", expanded=False):
        st.markdown(
            "1. Press **Join with camera** and allow the camera.\n"
            "2. **Just sign.** Each recognised word appears instantly as a subtitle on your video for everyone — "
            "no letter-by-letter spelling.\n"
            "3. **Lower your hands for ~3 seconds** → the sentence is finished and saved to the chat. Or press **📤 Send now**.\n"
            "4. Open **➕ Teach the app your own word** to add any word in *your* way of signing (2–3 recordings each).\n"
            "5. Use ⌫ **Undo word** or 🗑️ **Clear** to fix mistakes.")
    render_video_call({"id": meeting_id}, {"id": user_id, "name": user_name, "role": user_role}, sign=True)
    _sign_log_fragment((meeting_id, user_id, user_name, user_role))
