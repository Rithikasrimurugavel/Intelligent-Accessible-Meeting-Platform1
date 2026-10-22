import streamlit as st

from utils.config import Config

st.set_page_config(page_title=Config.APP_NAME, page_icon="🌐", layout="wide")

from services.huggingface_service import huggingface_service  # noqa: E402
from services.supabase_service import supabase_service  # noqa: E402
from views.login import render_login_page  # noqa: E402
from views.meeting_room import render_meeting_room_page  # noqa: E402
from views.role_selection import render_role_selection_page  # noqa: E402
from components.voice_assistant import render_voice_assistant  # noqa: E402

st.session_state.setdefault("current_page", "login")
st.session_state.setdefault("user", None)
st.session_state.setdefault("current_meeting", None)
st.session_state.setdefault("voice_guidance_enabled", Config.ENABLE_VOICE_GUIDANCE_DEFAULT)

st.session_state.setdefault("voice_mode", False)

# Voice assistant switches: ?voice=1 in the URL, or automatically once for users whose role is "blind".
if not st.session_state.get("_voice_param_checked"):
    st.session_state["_voice_param_checked"] = True
    if str(st.query_params.get("voice", "")).lower() in ("1", "true", "on", "yes"):
        st.session_state["voice_mode"] = True
user = st.session_state["user"]
if user and user.get("role") == "blind" and not st.session_state.get("_voice_auto_checked"):
    st.session_state["_voice_auto_checked"] = True
    st.session_state["voice_mode"] = True

with st.sidebar:
    st.markdown(f"## 🌐 {Config.APP_NAME}")
    st.caption(Config.TAGLINE)
    st.caption(f"💾 Storage: {'Supabase' if supabase_service.use_supabase else 'In-memory (demo)'}")
    st.caption(f"🤗 AI: {'Hugging Face live ✅' if huggingface_service.is_live else 'Hugging Face key NOT active (see Sign page for why)'}")
    st.session_state["sidebar_voice_toggle"] = st.session_state["voice_mode"]   # keep the widget in sync
    _voice_now = st.toggle("🎙️ Voice assistant (hands-free, for blind users)", key="sidebar_voice_toggle")
    if _voice_now != st.session_state["voice_mode"]:
        st.session_state["voice_mode"] = _voice_now
        st.rerun()
    if user:
        st.markdown("---")
        st.markdown(f"**{user['name']}** · `{user['role']}`")
        if st.button("🔁 Switch role", key="sidebar_switch_role"):
            st.session_state["current_page"] = "role_selection"
            st.rerun()
        if st.button("⏏️ Log out", key="sidebar_logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

# The voice assistant lives in a slot at the TOP of the page but is drawn LAST, so anything the page decides
# to announce during this run is already in its queue.
voice_slot = st.container()

if not user:
    render_login_page()
elif st.session_state["current_page"] == "meeting_room":
    render_meeting_room_page()
else:
    render_role_selection_page()

if st.session_state.get("voice_mode"):
    with voice_slot:
        render_voice_assistant()
