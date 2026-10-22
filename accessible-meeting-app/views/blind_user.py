import streamlit as st

from components.accessibility import (inject_accessibility_css, render_voice_guidance_toggle,
                                      speak_voice_guidance)
from components.speech_to_text import render_speech_to_text_widget
from components.text_to_speech import render_tts_player
from components.video_call import render_video_call
from services.message_service import message_service
from utils.config import Config
from utils.helpers import esc, html_block


@st.fragment(run_every=Config.REFRESH_SECONDS)
def _incoming_messages(meeting_id: str, user_id: str):
    messages = message_service.get_meeting_messages(meeting_id)
    if not messages:
        st.info("No messages in the meeting yet. Speak above to send the first message!")
        return

    latest = messages[-1]
    sender = latest.get("sender_name", "Participant")
    role = (latest.get("sender_role") or "normal").upper()
    text = latest.get("text_content", "")

    st.markdown(html_block(f"""
        <div class="accessible-card" style="border-left:8px solid #d97706;background-color:#fffbe6;">
          <h3 style="margin:0;color:#92400e;">📢 Latest Message from {esc(sender)} ({esc(role)})</h3>
          <p style="font-size:1.5rem;color:#78350f;font-weight:600;margin-top:10px;">"{esc(text)}"</p>
        </div>"""), unsafe_allow_html=True)

    render_tts_player(text, auto_play=False, key="blind_latest_msg")

    # Auto-announce new messages from other people (once each). In voice-assistant mode the assistant does this.
    if not st.session_state.get("voice_mode") and str(latest.get("sender_id")) != str(user_id):
        speak_voice_guidance(f"New message from {sender}: {text}", key_suffix=str(latest.get("id", "")))

    with st.expander("📜 Full Meeting Conversation History", expanded=False):
        for msg in messages:
            st.write(f"**{msg.get('sender_name')}** ({msg.get('sender_role')}): {msg.get('text_content')}")


def render_blind_user_interface(meeting: dict, user: dict):
    inject_accessibility_css()
    st.markdown("## 👁️ ACCESSIBLE VOICE INTERFACE")
    st.markdown(f"### Meeting: **{meeting['title']}** (`{meeting['meeting_code']}`)")
    st.success("🟢 Connected to Voice Channel")
    render_video_call(meeting, user)          # audio-only for blind users (no camera / video needed)

    if st.session_state.get("voice_mode"):
        st.info("🎙️ **Voice assistant is listening.** Say “start talking” and everything you say goes to the meeting. "
                "Say “stop talking” to return to commands. Other commands: “read last message”, “who is here”, "
                "“meeting code”, “enable audio”, “disable audio”, “leave meeting”, “help”.")
    else:
        speak_voice_guidance(
            f"Welcome {user['name']}. You are in meeting {meeting['title']}. "
            "Microphone is ready. Use the record button below to talk.", key_suffix=meeting["id"])
        st.warning("Turn on the 🎙️ Voice assistant in the sidebar for hands-free control.")
    render_voice_guidance_toggle()

    st.markdown("---")
    st.markdown("### 🎙️ STEP 1: SPEAK TO COMMUNICATE")
    if st.session_state.get("voice_mode"):
        st.caption("Backup option: record a single message with the button below.")
    render_speech_to_text_widget(meeting["id"], user["id"], user["name"], "blind")

    st.markdown("---")
    st.markdown("### 🔊 STEP 2: INCOMING MESSAGES & READOUT")
    _incoming_messages(meeting["id"], user["id"])
