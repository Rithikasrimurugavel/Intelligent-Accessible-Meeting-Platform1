import streamlit as st

from components.accessibility import inject_accessibility_css
from components.chat import render_chat_feed, render_typed_input_box
from components.meeting_controls import render_manager_controls, render_meeting_header
from components.speech_to_text import render_speech_to_text_widget
from components.video_call import render_video_call
from services.meeting_service import meeting_service
from utils.helpers import get_role_display_name, get_role_icon


def render_manager_dashboard(meeting: dict, user: dict):
    inject_accessibility_css()
    st.markdown("## 👑 MEETING MANAGER DASHBOARD")
    render_meeting_header(meeting, user_role="manager")
    render_video_call(meeting, user)

    with st.sidebar:
        st.markdown("### ⚙️ Meeting Controls")
        render_manager_controls(meeting, user)
        st.markdown("---")
        st.markdown("### 👥 Participant List")
        participants = meeting_service.get_participants(meeting["id"])
        st.metric("Total Active Participants", len(participants))
        for p in participants:
            role = p.get("role", "normal")
            st.markdown(f"🟢 **{p.get('name', 'Participant')}** {get_role_icon(role)} (*{get_role_display_name(role)}*)")

    col_chat, col_respond = st.columns([3, 2])
    with col_chat:
        render_chat_feed(meeting["id"], current_user_id=user["id"])

    with col_respond:
        st.markdown("### 📢 Broadcast Response")
        st.caption("Broadcast as text, audio for blind users, and subtitles for deaf users.")
        tab_type, tab_voice = st.tabs(["💬 Type Response", "🎤 Speak Response"])
        with tab_type:
            render_typed_input_box(meeting["id"], user["id"], user["name"], "manager", key_suffix="mgr_dash")
        with tab_voice:
            render_speech_to_text_widget(meeting["id"], user["id"], user["name"], "manager")
