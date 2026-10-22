import streamlit as st

from components.accessibility import inject_accessibility_css
from components.chat import render_chat_feed, render_typed_input_box
from components.speech_to_text import render_speech_to_text_widget
from components.video_call import render_video_call
from services.meeting_service import meeting_service


def render_normal_user_interface(meeting: dict, user: dict):
    inject_accessibility_css()
    st.markdown("## 👤 NORMAL PARTICIPANT INTERFACE")
    st.markdown(f"### Meeting: **{meeting['title']}** (`{meeting['meeting_code']}`)")
    st.success("🟢 Audio Channel Connected")
    render_video_call(meeting, user)

    col_main, col_side = st.columns([3, 2])
    with col_main:
        st.markdown("### 🎙️ Speak to Meeting")
        render_speech_to_text_widget(meeting["id"], user["id"], user["name"], "normal")
        st.markdown("---")
        render_chat_feed(meeting["id"], current_user_id=user["id"])

    with col_side:
        st.markdown("### 💬 Type Message")
        render_typed_input_box(meeting["id"], user["id"], user["name"], "normal", key_suffix="normal_user")
        st.markdown("---")
        st.markdown("#### 👥 Active Participants")
        for p in meeting_service.get_participants(meeting["id"]):
            st.markdown(f"• **{p.get('name')}** ({str(p.get('role', '')).upper()})")
