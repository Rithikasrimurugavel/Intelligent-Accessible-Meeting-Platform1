import streamlit as st


def show_notification(message: str, type_: str = "info"):
    """Display an accessible notification banner."""
    if type_ == "success":
        st.success(f"✅ {message}")
    elif type_ == "warning":
        st.warning(f"⚠️ {message}")
    elif type_ == "error":
        st.error(f"❌ {message}")
    else:
        st.info(f"ℹ️ {message}")
