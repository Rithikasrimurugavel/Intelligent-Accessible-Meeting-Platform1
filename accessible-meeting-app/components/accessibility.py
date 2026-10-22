import json

import streamlit as st

_CSS = """
<style>
.stApp { font-family: 'Segoe UI', Arial, sans-serif; }
.accessible-card { background-color: #f8fafc; border: 2px solid #3b82f6; border-radius: 12px; padding: 18px;
  margin-bottom: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); color: #0f172a; }
.accessible-card-subtitle { background-color: #0f172a; color: #ffffff; border-left: 6px solid #eab308;
  padding: 24px; border-radius: 8px; font-size: 1.4rem; line-height: 1.6; margin: 16px 0; }
.badge-manager { background-color: #7c3aed; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
.badge-normal { background-color: #2563eb; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
.badge-blind { background-color: #b45309; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
.badge-deaf { background-color: #047857; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
.badge-mute { background-color: #dc2626; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
.badge-system { background-color: #475569; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
.stButton > button { min-height: 52px; font-size: 1.1rem; font-weight: 600; border-radius: 10px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
</style>
"""


def inject_accessibility_css():
    """Inject high-contrast, accessible CSS."""
    st.markdown(_CSS, unsafe_allow_html=True)


def speak_voice_guidance(text: str, key_suffix: str = ""):
    """
    Speak `text` with the browser SpeechSynthesis API (Voice Guidance for blind users).
    Each distinct announcement is spoken once per session so reruns don't repeat it.
    Note: browsers may block speech until the user has interacted with the page once.
    """
    if not st.session_state.get("voice_guidance_enabled", True):
        return
    spoken = st.session_state.setdefault("_spoken_guidance", set())
    token = f"{text}|{key_suffix}"
    if token in spoken:
        return
    if len(spoken) > 500:
        spoken.clear()
    spoken.add(token)

    # Voice assistant active: use its single speech channel (so announcements never talk over each other).
    if st.session_state.get("voice_mode"):
        from services.voice_agent import VoiceAgent
        VoiceAgent(st.session_state).say(text, remember=False)
        return

    safe_js_string = json.dumps(text).replace("</", "<\\/")
    script = f"""<script>
    if ('speechSynthesis' in window) {{
        window.speechSynthesis.cancel();
        var u = new SpeechSynthesisUtterance({safe_js_string});
        u.rate = 1.0; u.pitch = 1.0; u.volume = 1.0;
        window.speechSynthesis.speak(u);
    }}
    </script>"""
    # st.components.v1.html is deprecated in newer Streamlit; prefer st.iframe when available.
    if hasattr(st, "iframe"):
        st.iframe(script, height=1)
    else:
        st.components.v1.html(script, height=0)


def render_voice_guidance_toggle():
    enabled = st.session_state.get("voice_guidance_enabled", True)
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"**🔊 Voice Guidance:** {'`ENABLED`' if enabled else '`DISABLED`'}")
    with col2:
        if st.button("Disable Guidance" if enabled else "Enable Guidance", key="btn_toggle_guidance"):
            st.session_state["voice_guidance_enabled"] = not enabled
            st.rerun()
