from datetime import datetime

import streamlit as st

from services.message_service import message_service
from utils.config import Config
from utils.helpers import (esc, format_timestamp, get_role_display_name, get_role_icon, html_block)

_VALID_BADGES = {"manager", "normal", "blind", "deaf", "mute", "system"}


@st.fragment(run_every=Config.REFRESH_SECONDS)
def render_chat_feed(meeting_id: str, current_user_id: str):
    """Live conversation feed (auto-refreshes every few seconds)."""
    st.markdown("### 💬 Live Meeting Conversation")
    messages = message_service.get_meeting_messages(meeting_id)

    if not messages:
        st.info("👋 No messages in this meeting yet. Start speaking, typing, or using sign language!")
        return

    for msg in messages:
        sender_role = (msg.get("sender_role") or "normal").lower()
        input_type = msg.get("input_type", "text")

        raw_ts = msg.get("timestamp")
        try:
            time_str = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).strftime("%H:%M:%S")
        except Exception:
            time_str = format_timestamp()

        input_icon = {"voice": "🎤", "sign_language": "🖐️", "system": "📢"}.get(input_type, "💬")
        badge = f"badge-{sender_role}" if sender_role in _VALID_BADGES else "badge-normal"
        is_me = bool(msg.get("sender_id")) and str(msg.get("sender_id")) == str(current_user_id)
        border = "#3b82f6" if is_me else "#94a3b8"

        st.markdown(html_block(f"""
            <div style="background:#ffffff;border-left:6px solid {border};border-radius:8px;padding:12px 16px;
                        margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;">
                <div>
                  <span style="font-weight:700;font-size:1.05rem;margin-right:8px;color:#0f172a;">
                    {esc(msg.get('sender_name', 'Unknown'))} {get_role_icon(sender_role)}</span>
                  <span class="{badge}">{esc(get_role_display_name(sender_role))}</span>
                </div>
                <div style="color:#475569;font-size:0.85rem;">{input_icon} {esc(input_type.replace('_', ' ').title())} • {esc(time_str)}</div>
              </div>
              <div style="font-size:1.1rem;color:#1e293b;line-height:1.5;margin-top:4px;">{esc(msg.get('text_content', ''))}</div>
            </div>"""), unsafe_allow_html=True)


def render_typed_input_box(meeting_id: str, user_id: str, user_name: str, user_role: str, key_suffix: str = ""):
    """Text input box for typed messages."""
    with st.form(key=f"typed_chat_form_{key_suffix}", clear_on_submit=True):
        col1, col2 = st.columns([5, 1])
        with col1:
            user_text = st.text_input("Type your message", placeholder="Type your response here...",
                                      label_visibility="collapsed", key=f"chat_input_text_{key_suffix}")
        with col2:
            submit = st.form_submit_button("Send 💬", type="primary")

        if submit:
            if not user_text.strip():
                st.warning("Please type a message first.")
                return
            ok, _msg, status = message_service.send_text_message(
                meeting_id=meeting_id, sender_id=user_id, sender_name=user_name,
                sender_role=user_role, text=user_text)
            if ok:
                st.rerun()
            else:
                st.error(status)
