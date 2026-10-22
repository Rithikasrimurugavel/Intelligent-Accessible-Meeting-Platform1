import streamlit as st

from components.accessibility import inject_accessibility_css, speak_voice_guidance
from services.user_service import user_service
from utils.helpers import html_block


def render_login_page():
    inject_accessibility_css()
    st.markdown(html_block("""
        <div style="text-align:center;margin-bottom:24px;">
          <h1 style="color:#1e3a8a;font-size:2.5rem;">🌐 ACCESSIBLE MEETING APP</h1>
          <p style="font-size:1.2rem;color:#475569;">"Communication Without Barriers"</p>
        </div>"""), unsafe_allow_html=True)

    if st.session_state.get("voice_mode"):
        st.info("🎙️ Voice assistant is on. Say “create account” or “log in”. Say “help” for all commands.")
    else:
        speak_voice_guidance("Welcome to the Accessible Meeting App. Please log in or create a profile to continue.")
        st.markdown("### 👁️ Blind or low vision?")
        st.caption("Create an account, log in, create or join meetings, and enable audio entirely by voice.")
        if st.button("🎙️ Start Voice Assistant (hands-free)", key="btn_start_voice_assistant", type="primary"):
            st.session_state["voice_mode"] = True
            st.rerun()

    tab1, tab2 = st.tabs(["🔑 Quick Login", "📝 Create User Profile"])

    with tab1:
        st.markdown("### Enter Your Profile Info")
        with st.form("login_form"):
            email = st.text_input("Email Address", placeholder="name@example.com")
            name = st.text_input("Full Name (new users)", placeholder="John Doe")
            submitted = st.form_submit_button("Proceed to Role Selection 🚀", type="primary")
        if submitted:
            ok, profile, msg = user_service.login_user(name=name.strip(), email=email.strip())
            if ok and profile:
                st.session_state["user"] = profile
                st.session_state["current_page"] = "role_selection"
                st.rerun()
            else:
                st.error(msg)

    with tab2:
        st.markdown("### Register New Accessible Profile")
        role_labels = {
            "manager": "👑 Meeting Host / Manager",
            "normal": "👤 Normal Participant (Voice)",
            "blind": "👁️ Visually Impaired / Blind (Voice Guidance)",
            "deaf": "🧏‍♂️ Deaf / Hearing Impaired (Subtitles & Text)",
            "mute": "🖐️ Mute / Speech Impaired (Sign Language Camera)",
        }
        with st.form("register_form"):
            reg_name = st.text_input("Full Name", placeholder="Jane Smith")
            reg_email = st.text_input("Email Address", placeholder="jane@example.com")
            reg_role = st.selectbox("Primary Accessibility Role", options=list(role_labels),
                                    format_func=lambda r: role_labels[r])
            reg_submit = st.form_submit_button("Create Profile & Continue ➡️", type="primary")
        if reg_submit:
            ok, profile, msg = user_service.register_user(name=reg_name, email=reg_email, role=reg_role)
            if ok and profile:
                st.session_state["user"] = profile
                st.session_state["current_page"] = "role_selection"
                st.rerun()
            else:
                st.error(msg)
