import streamlit as st

from components.accessibility import inject_accessibility_css, speak_voice_guidance
from services.call_service import call_service
from services.meeting_service import meeting_service
from services.message_service import message_service
from utils.helpers import esc
from views.blind_user import render_blind_user_interface
from views.hearing_impaired import render_hearing_impaired_interface
from views.manager_dashboard import render_manager_dashboard
from views.mute_user import render_mute_user_interface
from views.normal_user import render_normal_user_interface
from views.post_meeting_summary import render_post_meeting_summary, render_summary_lobby_tab


def _enter_meeting(meeting: dict, user: dict, announcement: str):
    st.session_state["current_meeting"] = meeting
    speak_voice_guidance(announcement, key_suffix=meeting["id"])


def render_meeting_room_page():
    inject_accessibility_css()
    user = st.session_state.get("user")
    if not user:
        st.session_state["current_page"] = "login"
        st.rerun()

    meeting = st.session_state.get("current_meeting")

    # Keep the local meeting copy fresh (e.g. host ended it).
    if meeting:
        fresh = meeting_service.refresh_meeting(meeting["meeting_code"])
        if fresh:
            meeting = fresh
            st.session_state["current_meeting"] = fresh

    # ------------------------------------------------------------------ Lobby
    if not meeting:
        st.markdown("## 🏢 Accessible Meeting Lobby")
        st.markdown(f"**Logged in as:** {esc(user['name'])} | **Role:** `{user['role'].upper()}`")
        tab_join, tab_create, tab_summary = st.tabs(
            ["🚪 Join Existing Meeting", "➕ Create New Meeting", "📝 Summarize Post Meeting"])

        with tab_join:
            with st.form("join_meeting_form"):
                code = st.text_input("Meeting Code", placeholder="AM-8F3K92").strip()
                join = st.form_submit_button("Join Meeting 🚪", type="primary")
            if join:
                if not code:
                    st.error("Please enter a meeting code.")
                else:
                    ok, m, _p, msg = meeting_service.join_meeting(code, user["id"], user["role"])
                    if ok and m:
                        message_service.send_system_message(
                            m["id"], f"👋 {user['name']} joined the meeting as {user['role'].upper()}.")
                        _enter_meeting(m, user, f"Meeting joined. Welcome to {m['title']}.")
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_create:
            with st.form("create_meeting_form"):
                title = st.text_input("Meeting Title", placeholder="Accessible Team Discussion")
                create = st.form_submit_button("Create & Start Meeting 🚀", type="primary")
            if create:
                ok, m, msg = meeting_service.create_meeting(title=title, host_id=user["id"])
                if ok and m:
                    # join by CODE (not id) so the host is registered as a participant
                    meeting_service.join_meeting(m["meeting_code"], user["id"], user["role"])
                    message_service.send_system_message(m["id"], f"🚀 Meeting '{m['title']}' started by {user['name']}.")
                    _enter_meeting(m, user, f"Meeting created. The meeting code is {m['meeting_code']}.")
                    st.rerun()
                else:
                    st.error(msg)

        with tab_summary:
            render_summary_lobby_tab(user)
        return

    # ------------------------------------------------------------------ Ended
    if meeting.get("status") == "ended":
        st.warning(f"🔴 '{meeting['title']}' has ended.")
        if st.button("Return to Lobby", type="primary"):
            st.session_state["current_meeting"] = None
            st.rerun()
        st.markdown("---")
        st.markdown("## 📝 Summarize Post Meeting")
        render_post_meeting_summary(meeting, user)
        return

    # ------------------------------------------------------------------ Active
    _, col_leave = st.columns([5, 1])
    with col_leave:
        if st.button("🚪 Leave Meeting"):
            meeting_service.leave_meeting(meeting["id"], user["id"])
            call_service.leave(meeting["id"], uid=user["id"])
            message_service.send_system_message(meeting["id"], f"🚪 {user['name']} left the meeting.")
            st.session_state["current_meeting"] = None
            speak_voice_guidance("You have left the meeting.", key_suffix=meeting["id"])
            st.rerun()

    role = user.get("role", "normal").lower()
    if role == "manager":
        render_manager_dashboard(meeting, user)
    elif role == "blind":
        render_blind_user_interface(meeting, user)
    elif role == "deaf":
        render_hearing_impaired_interface(meeting, user)
    elif role == "mute":
        render_mute_user_interface(meeting, user)
    else:
        render_normal_user_interface(meeting, user)
