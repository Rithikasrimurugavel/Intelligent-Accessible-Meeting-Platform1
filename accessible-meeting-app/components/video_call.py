"""
Live video meeting for every role (Zoom-style tiles).

* Camera + microphone for host, normal, deaf and sign-language users; blind users join audio-only (no video needed).
* Video and audio flow browser-to-browser (WebRTC); this module only shuttles the tiny connection messages.
* Spoken words are turned into live subtitles by the speaker's own browser; a sign-language user's signs are read from
  their own camera and sent as live subtitles. Subtitles are shown on top of the video for everybody and every finished
  sentence is also saved to the meeting conversation (so the subtitle panel / read-aloud features keep working).
"""
from typing import Any, Callable, Dict

import streamlit as st

from components.video_meeting import video_meeting
from services.call_service import call_service
from services.message_service import message_service
from utils.config import Config

_MAX_EVENTS = 40


def call_config(role: str, sign: bool = False, voice_mode: bool = False) -> Dict[str, Any]:
    """What each role sends / sees in the call."""
    role = (role or "normal").lower()
    return {
        "cam": role != "blind",                         # blind users do not need a camera
        "mic": role != "mute",                          # speech-impaired users sign instead of speaking
        "show_video": role != "blind",                  # ...and do not need to see the video tiles
        "sign": bool(sign) or role == "mute",           # read signs from this user's own camera
        # spoken words -> subtitles. Off while the voice assistant is on: both use the browser's single speech recogniser
        "speech": role in ("manager", "normal", "blind") and not voice_mode,
        "lang": Config.VOICE_LANG,
    }


def process_batch(meeting_id: str, user: Dict[str, Any], batch: Dict[str, Any],
                  on_sign_sentence: Callable[[Dict[str, Any]], None]) -> int:
    """Apply one batch of browser events. Returns the number of events handled. Pure Python (unit-testable)."""
    sid = str(batch.get("sid") or "")[:40]
    if not sid:
        return 0
    n = 0
    for ev in (batch.get("events") or [])[:_MAX_EVENTS]:
        if not isinstance(ev, dict):
            continue
        t = ev.get("t")
        if t == "hello":
            call_service.heartbeat(meeting_id, sid, user["id"], user["name"], user.get("role", "normal"))
        elif t == "sig":
            call_service.push(meeting_id, sid, str(ev.get("to") or ""), ev.get("data"))
        elif t == "caption":
            text = str(ev.get("text") or "").strip()[:500]
            if not text:
                continue
            try:
                conf = min(1.0, max(0.0, float(ev.get("conf", 0.85))))
            except (TypeError, ValueError):
                conf = 0.85
            message_service.send_voice_text_message(meeting_id, user["id"], user["name"],
                                                    user.get("role", "normal"), text, conf)
        elif t == "sign":
            on_sign_sentence({"words": ev.get("words"), "conf": ev.get("conf", 0.85)})
        else:
            continue
        n += 1
    return n


@st.fragment(run_every=0.7)
def _call_fragment(meeting_id: str, user_id: str, user_name: str, user_role: str, sign: bool):
    from components.sign_language import handle_sign_sentence      # local import: avoids a circular import

    user = {"id": user_id, "name": user_name, "role": user_role}
    ctx = (meeting_id, user_id, user_name, user_role)
    sid = st.session_state.get("_vc_sid")
    if sid:
        call_service.heartbeat(meeting_id, sid, user_id, user_name, user_role)

    batch = video_meeting(
        me={"name": user_name, "role": user_role, "uid": str(user_id)},
        peers=call_service.peers(meeting_id, sid) if sid else [],
        signals=call_service.inbox(meeting_id, sid) if sid else [],
        ack=st.session_state.get("_vc_ack", ""),
        cfg=call_config(user_role, sign, bool(st.session_state.get("voice_mode"))),
        ice_servers=Config.ice_servers(),
        sentence_pause=Config.SIGN_LIVE_SENTENCE_PAUSE_SECONDS,
        key=f"video_meeting_{meeting_id}")

    if isinstance(batch, dict) and batch.get("id") and batch["id"] != st.session_state.get("_vc_ack"):
        st.session_state["_vc_sid"] = str(batch.get("sid") or "")[:40]
        process_batch(meeting_id, user, batch, lambda ev: handle_sign_sentence(ev, ctx))
        st.session_state["_vc_ack"] = batch["id"]
        st.rerun(scope="fragment")            # hand the acknowledgement back to the browser right away


def render_video_call(meeting: dict, user: dict, sign: bool = False):
    """Draw the live video meeting for this user (one call per page)."""
    _call_fragment(meeting["id"], user["id"], user["name"], user.get("role", "normal"), sign)
