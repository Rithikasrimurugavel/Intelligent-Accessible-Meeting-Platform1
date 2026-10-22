import streamlit as st

from components.accessibility import inject_accessibility_css
from components.chat import render_chat_feed, render_typed_input_box
from components.sign_language import render_sign_language_component


def render_mute_user_interface(meeting: dict, user: dict):
    inject_accessibility_css()
    st.markdown("## 🖐️ SIGN LANGUAGE CAMERA INTERFACE")
    st.markdown(f"### Meeting: **{meeting['title']}** (`{meeting['meeting_code']}`)")
    st.success("🟢 Camera Sign Language Engine Ready")

    render_sign_language_component(meeting["id"], user["id"], user["name"], "mute")
    st.markdown("---")
    col_sign, col_chat = st.columns(2)
    with col_sign:
        st.markdown("#### ⌨️ Alternative Text Input")
        st.caption("You can also type text responses directly:")
        render_typed_input_box(meeting["id"], user["id"], user["name"], "mute", key_suffix="mute_user_text")
    with col_chat:
        render_chat_feed(meeting["id"], current_user_id=user["id"])
