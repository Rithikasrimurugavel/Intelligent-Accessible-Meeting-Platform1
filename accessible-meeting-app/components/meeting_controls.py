import streamlit as st

from services.meeting_service import meeting_service
from services.message_service import message_service
from utils.helpers import esc


def render_meeting_header(meeting_dict: dict, user_role: str = ""):
    title = meeting_dict.get("title", "Accessible Meeting")
    code = meeting_dict.get("meeting_code", "AM-000000")
    status = str(meeting_dict.get("status", "active")).upper()

    col1, col2, col3 = st.columns([3, 2, 2])
    with col1:
        st.subheader(f"📌 {title}")
    with col2:
        st.markdown(f"**Meeting Code:** `{code}`")
    with col3:
        st.markdown(f"**Status:** {'🟢 LIVE' if status == 'ACTIVE' else '🔴 ENDED'}")


def render_manager_controls(meeting: dict, user: dict):
    st.markdown("#### ⚙️ Host Controls")
    st.caption("Share this meeting code (use the copy icon):")
    st.code(meeting["meeting_code"], language=None)

    if str(meeting.get("host_id")) != str(user["id"]):
        st.caption("Only the person who created this meeting can end it.")
        return

    if st.button("🛑 End Meeting for All", type="primary"):
        message_service.send_system_message(meeting["id"], "🛑 The host ended the meeting.")
        if meeting_service.end_meeting(meeting["id"]):
            # Stay on the meeting: the room now shows "ended" + the post-meeting summary section.
            st.rerun()
        else:
            st.error("Could not end the meeting. Please try again.")
