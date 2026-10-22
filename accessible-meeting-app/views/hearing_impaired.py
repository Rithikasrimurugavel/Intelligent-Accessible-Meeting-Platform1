import streamlit as st

from components.accessibility import inject_accessibility_css
from components.chat import render_typed_input_box
from components.subtitles import render_subtitles_panel
from components.video_call import render_video_call
from services.meeting_service import meeting_service


def render_hearing_impaired_interface(meeting: dict, user: dict):
    inject_accessibility_css()
    st.markdown("## 🧏‍♂️ ACCESSIBLE SUBTITLE & TEXT INTERFACE")
    st.markdown(f"### Meeting: **{meeting['title']}** (`{meeting['meeting_code']}`)")
    st.success("🟢 Subtitle Stream Active")
    render_video_call(meeting, user)

    col_sub, col_input = st.columns([3, 2])
    with col_sub:
        render_subtitles_panel(meeting["id"])
    with col_input:
        st.markdown("### ⌨️ TYPE YOUR RESPONSE")
        st.caption("Your response is published to everyone and read aloud for blind participants.")
        render_typed_input_box(meeting["id"], user["id"], user["name"], "deaf", key_suffix="deaf_user")

    st.markdown("---")
    st.markdown("#### 👥 Meeting Participants")
    for p in meeting_service.get_participants(meeting["id"]):
        st.markdown(f"• **{p.get('name')}** ({str(p.get('role', '')).upper()})")
