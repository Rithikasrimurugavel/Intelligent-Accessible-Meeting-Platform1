import streamlit as st

from components.accessibility import inject_accessibility_css, speak_voice_guidance
from services.meeting_service import meeting_service
from services.user_service import user_service
from utils.helpers import esc, get_role_display_name, html_block

ROLES = [
    {"id": "manager", "title": "👑 Meeting Manager / Host", "color": "#7c3aed",
     "desc": "Host meetings, view unified multi-modal messages, control meeting status, respond via text or voice."},
    {"id": "normal", "title": "👤 Normal Participant", "color": "#2563eb",
     "desc": "Speak with automatic Speech-to-Text, view the live chat feed, type text responses."},
    {"id": "blind", "title": "👁️ Visually Impaired / Blind", "color": "#d97706",
     "desc": "Voice-first interface, high-contrast UI, spoken announcements (Voice Guidance), audio readout of messages."},
    {"id": "deaf", "title": "🧏‍♂️ Deaf / Hearing Impaired", "color": "#059669",
     "desc": "Large high-contrast live subtitles, speaker badges, keyboard text responses."},
    {"id": "mute", "title": "🖐️ Mute / Speech Impaired", "color": "#dc2626",
     "desc": "Camera sign recognition (Hugging Face vision model), detected-sign preview, text conversion."},
]


def render_role_selection_page():
    inject_accessibility_css()
    user = st.session_state.get("user")
    if not user:
        st.session_state["current_page"] = "login"
        st.rerun()

    st.markdown(f"## 👋 Welcome, {esc(user['name'])}")
    st.markdown("### Select Your Meeting Role & Communication Interface")
    st.caption("Choose how you prefer to communicate. The interface adapts to your needs.")
    speak_voice_guidance("Role selection. Please select your meeting role: Host, Normal, Blind, Deaf, or Mute.")

    for role in ROLES:
        st.markdown(html_block(f"""
            <div class="accessible-card" style="border-left:8px solid {role['color']};">
              <h3 style="margin:0;color:#0f172a;">{role['title']}</h3>
              <p style="color:#475569;font-size:1.05rem;margin-top:8px;">{role['desc']}</p>
            </div>"""), unsafe_allow_html=True)

        if st.button(f"Select Role: {role['title']}", key=f"btn_role_{role['id']}"):
            ok, profile, msg = user_service.update_role(user, role["id"])
            if not ok:
                st.error(msg)
                continue
            st.session_state["user"] = profile
            meeting = st.session_state.get("current_meeting")
            if meeting:  # keep participant record in sync if switching role mid-meeting
                meeting_service.join_meeting(meeting["meeting_code"], profile["id"], role["id"])
            speak_voice_guidance(f"Role set to {get_role_display_name(role['id'])}. Proceeding to meeting room.",
                                 key_suffix=role["id"])
            st.session_state["current_page"] = "meeting_room"
            st.rerun()
