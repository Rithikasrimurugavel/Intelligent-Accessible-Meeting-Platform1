import streamlit as st

from services.message_service import message_service
from utils.config import Config
from utils.helpers import esc, get_role_icon, html_block


@st.fragment(run_every=Config.REFRESH_SECONDS)
def render_subtitles_panel(meeting_id: str):
    """High-contrast, large-font live subtitles for Deaf / hard-of-hearing users."""
    st.markdown("### 🧏‍♂️ REAL-TIME ACCESSIBLE SUBTITLES")
    messages = message_service.get_meeting_messages(meeting_id)

    if not messages:
        st.markdown(html_block("""
            <div class="accessible-card-subtitle" style="text-align:center;">
              <p style="margin:0;color:#cbd5e1;font-style:italic;">
                Subtitles active. Waiting for participants to speak, type, or use sign language...</p>
            </div>"""), unsafe_allow_html=True)
        return

    latest = messages[-1]
    role = (latest.get("sender_role") or "normal")
    st.markdown(html_block(f"""
        <div class="accessible-card-subtitle">
          <div style="font-size:0.95rem;color:#eab308;font-weight:700;text-transform:uppercase;
                      letter-spacing:1px;margin-bottom:8px;">
            🔴 CURRENT SPEAKER: {esc(latest.get('sender_name', 'Speaker'))} {get_role_icon(role)} ({esc(role.upper())})</div>
          <div style="font-size:1.8rem;font-weight:600;color:#ffffff;line-height:1.4;">
            "{esc(latest.get('text_content', ''))}"</div>
        </div>"""), unsafe_allow_html=True)

    with st.expander("📜 View Recent Subtitle History", expanded=True):
        for msg in reversed(messages[:-1][-30:]):
            icon = get_role_icon(msg.get("sender_role", "normal"))
            st.markdown(f"**{msg.get('sender_name', 'Speaker')} {icon}**: {msg.get('text_content', '')}")
