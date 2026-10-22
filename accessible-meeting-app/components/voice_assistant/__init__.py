"""
Voice assistant panel: continuous listening + spoken replies in the browser (Web Speech API, Chrome / Edge),
with the decision making done in Python by services.voice_agent.VoiceAgent.

Because the panel is an st.fragment it polls every few seconds (to announce new meeting messages) without
re-running the whole app, and it only triggers a full rerun when a spoken command changes the page.
"""
import hashlib
import os

import streamlit as st
import streamlit.components.v1 as components

from services.huggingface_service import huggingface_service
from services.voice_agent import VoiceAgent
from utils.config import Config

_component = components.declare_component(
    "accessible_voice_assistant", path=os.path.join(os.path.dirname(__file__), "frontend"))


def _fallback_recorder(agent: VoiceAgent):
    """Push-to-record command, for browsers without continuous speech recognition (Firefox, Safari...)."""
    with st.expander("🎤 Voice assistant not listening? Record one command instead", expanded=False):
        audio = st.audio_input("Record a command, e.g. “create account”", key="va_fallback_audio") \
            if hasattr(st, "audio_input") else None
        if audio is None:
            return
        data = audio.getvalue()
        digest = hashlib.md5(data).hexdigest()
        if st.session_state.get("_va_fallback_digest") == digest:
            return
        st.session_state["_va_fallback_digest"] = digest
        with st.spinner("Understanding your command..."):
            res = huggingface_service.speech_to_text(data)
        if res.get("success"):
            agent.handle(res["text"])
        else:
            agent.say(res.get("error", "I could not understand the recording."))


@st.fragment(run_every=Config.VOICE_POLL_SECONDS)
def _voice_fragment():
    agent = VoiceAgent(st.session_state)
    agent.greet_if_needed()

    st.markdown("#### 🎙️ Voice Assistant")
    listening_sent = not agent.va["paused"]
    value = _component(queue=agent.va["queue"], listening=listening_sent, lang=Config.VOICE_LANG,
                       rate=Config.VOICE_RATE, sid=agent.va["sid"], key="va_component", default=None)

    signature = agent.queue_signature()
    if isinstance(value, dict) and value.get("id") and value["id"] != agent.va["last_event"]:
        agent.va["last_event"] = value["id"]
        kind = value.get("type")
        if kind == "speech":
            agent.handle(value.get("text", ""), value.get("confidence"))
        elif kind == "control" and value.get("action") == "resume":
            agent.va["paused"] = False
            agent.say("I am listening again.", remember=False)
        elif kind in ("error", "unsupported"):
            agent.say(value.get("text", "The voice assistant had a problem."), remember=False)
            st.warning(value.get("text", ""))

    agent.poll_incoming()
    _fallback_recorder(agent)

    if agent.navigate:
        st.rerun()                                  # a command changed the page -> redraw everything
    elif agent.queue_signature() != signature or (not agent.va["paused"]) != listening_sent:
        st.rerun(scope="fragment")                  # speak the new reply right away


def render_voice_assistant():
    _voice_fragment()
