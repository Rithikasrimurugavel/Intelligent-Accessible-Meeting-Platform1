"""📝 Summarize Post Meeting - works for every role (text, read-aloud audio, large high-contrast cards, download)."""
from datetime import datetime

import pandas as pd
import streamlit as st

from components.accessibility import inject_accessibility_css, speak_voice_guidance
from components.text_to_speech import render_tts_player
from services.meeting_service import meeting_service
from services.summary_service import NOT_SPECIFIED, summary_service
from utils.config import Config
from utils.helpers import esc, html_block


# ------------------------------------------------------------------ helpers
def _fmt_time(value) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M")
    except Exception:
        return ""


def _engine_status_line() -> str:
    if Config.is_groq_configured():
        return f"🧠 Summary engine: Groq ({Config.GROQ_MODEL}); Gemini / Hugging Face are used only if Groq fails"
    if Config.is_gemini_configured():
        return f"🧠 Summary engine: Gemini ({Config.GEMINI_MODEL}, falls back to another Gemini model if it is retired)"
    if Config.is_huggingface_configured():
        return f"🧠 Summary engine: Hugging Face ({Config.HUGGINGFACE_TEXT_MODEL})"
    return "🧠 No AI key set - a basic offline summary will be used (set GROQ_API_KEY or GEMINI_API_KEY for a proper one)."


def _card(title: str, body_html: str):
    st.markdown(html_block(f"""
        <div class="accessible-card"><h3 style="margin-top:0;color:#0f172a;">{esc(title)}</h3>
        <div style="font-size:1.15rem;line-height:1.6;">{body_html}</div></div>"""), unsafe_allow_html=True)


def _render_summary(meeting: dict, record: dict, user: dict):
    s = record["summary"]
    stats = s.get("stats") or {}

    st.markdown(f"## 📌 {s['title']}")
    bits = [f"Meeting code `{meeting.get('meeting_code', '')}`", f"engine: {record.get('engine', 'unknown')}",
            f"source: {'uploaded recording' if record.get('source') == 'recording' else 'meeting conversation'}"]
    if stats.get("duration_minutes") is not None:
        bits.append(f"duration: {stats['duration_minutes']} min")
    if record.get("generated_at"):
        bits.append(f"generated {_fmt_time(record['generated_at'])}")
    st.caption(" · ".join(bits))
    for w in s.get("warnings", []):
        st.warning(w)

    _card("📄 Summary", esc(s["summary"]))

    st.markdown("### ✅ Action Items")
    if s["action_items"]:
        df = pd.DataFrame(s["action_items"]).rename(columns={"task": "Task", "assigned_to": "Assigned to",
                                                             "deadline": "Deadline"})
        st.dataframe(df, hide_index=True, use_container_width=True)
        if all(a["assigned_to"] == NOT_SPECIFIED for a in s["action_items"]):
            st.caption("No owners were stated in the meeting - assign them before sharing.")
    else:
        st.info("No action items were identified.")

    col_dec, col_top = st.columns(2)
    with col_dec:
        st.markdown("### 🔑 Key Decisions")
        for d in s["key_decisions"] or ["None identified."]:
            st.markdown(f"- {d}")
    with col_top:
        st.markdown("### 🗂️ Topics Discussed")
        for t in s["topics_discussed"] or ["None identified."]:
            st.markdown(f"- {t}")

    speakers = stats.get("speakers") or []
    if speakers:
        st.markdown("### 📊 Participation")
        if "seconds" in (speakers[0] or {}):
            df = pd.DataFrame([{"Speaker": x["name"], "Talk time (s)": x["seconds"]} for x in speakers])
            st.caption("Measured from the recording (seconds of speech).")
        else:
            df = pd.DataFrame([{"Speaker": x["name"], "Words": x["words"]} for x in speakers])
            st.caption("Counted from what each person said, typed or signed (words), not from audio time.")
        st.bar_chart(df.set_index("Speaker"))

    st.markdown("### 🔊 Listen / 💾 Save")
    render_tts_player(summary_service.to_spoken_text(record), key=f"summary_{meeting['id']}")
    st.download_button("⬇️ Download summary (Markdown)", data=summary_service.to_markdown(meeting, record),
                       file_name=f"summary_{meeting.get('meeting_code', 'meeting')}.md", mime="text/markdown",
                       key=f"dl_{meeting['id']}")
    with st.expander("Show full transcript"):
        st.text(s.get("full_transcript", ""))


# ------------------------------------------------------------------ generation tabs
def _tab_conversation(meeting: dict, user: dict, saved: dict, is_host: bool):
    st.caption("Uses everything that was spoken, typed or signed in the meeting. Nothing to upload.")
    st.caption(_engine_status_line())
    if saved and not is_host:
        st.info("A summary already exists. Only the host can regenerate it.")
        return
    label = "🔄 Regenerate summary" if saved else "✨ Generate summary"
    if st.button(label, type="primary", key=f"gen_conv_{meeting['id']}"):
        with st.spinner("Reading the meeting conversation and writing the summary..."):
            ok, record, msg = summary_service.summarize_meeting(meeting, generated_by=user["id"])
        if ok:
            st.session_state["_announce_summary"] = meeting["id"]
            st.rerun()
        else:
            st.error(msg)


_MIME = {"wav": "audio/wav", "mp3": "audio/mp3", "m4a": "audio/mp4", "mp4": "video/mp4", "ogg": "audio/ogg",
         "flac": "audio/flac"}
_MODE_GROQ = "⚡ Quick - Groq Whisper transcribes the audio (no install, no speaker names)"
_MODE_GEMINI = "⚡ Quick - Gemini transcribes the audio (no speaker names)"
_MODE_LOCAL = "🎙️ Full - Whisper + pyannote on this PC (speaker names, slower)"


def _enroll_speakers_ui(ap):
    with st.expander("🗣️ Enrolled speakers (voiceprints) - Full mode only"):
        st.caption("A voiceprint is biometric data. Only enrol people who agreed, and delete it when they ask.")
        for i, sp in enumerate(ap.list_speakers()):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{esc(sp['name'])}**")
            if c2.button("Delete", key=f"del_sp_{i}"):
                ap.delete_speaker(sp["path"])
                st.rerun()
        with st.form("enroll_speaker_form", clear_on_submit=True):
            nm = st.text_input("Speaker name")
            sample = st.file_uploader("15-30 s clear sample of ONE person", type=["wav", "mp3", "m4a"])
            go = st.form_submit_button("Enroll speaker")
        if go and nm.strip() and sample:
            try:
                with st.spinner("Creating voiceprint..."):
                    ap.enroll_speaker(nm.strip(), sample.getvalue(), "." + sample.name.rsplit(".", 1)[-1])
                st.success(f"Enrolled {nm.strip()}.")
            except Exception as e:
                st.error(f"Enrollment failed: {e}")


def _tab_recording(meeting: dict, user: dict, is_host: bool):
    if not is_host:
        st.info("Only the host can summarise an uploaded recording.")
        return
    from services import audio_pipeline as ap

    # The uploader is ALWAYS shown. Which engines can run is decided here and explained, not hidden.
    missing = ap.missing_dependencies()
    local_ok = not missing and Config.is_huggingface_configured()
    gemini_ok = Config.is_gemini_configured()

    groq_ok = Config.is_groq_configured()
    modes = []
    if groq_ok:
        modes.append(_MODE_GROQ)
    if gemini_ok:
        modes.append(_MODE_GEMINI)
    if local_ok:
        modes.append(_MODE_LOCAL)

    st.caption("Upload the full meeting recording. It is transcribed, then summarised like the conversation summary.")
    if not local_ok:
        reasons = []
        if missing:
            reasons.append("not installed: **" + ", ".join(missing) + "** (`pip install -r requirements-audio.txt`, "
                           "and `ffmpeg` on PATH)")
        if not Config.is_huggingface_configured():
            reasons.append("HUGGINGFACE_API_KEY is not set (and the pyannote model terms must be accepted)")
        st.info("Full mode (Whisper + pyannote, real speaker names) is off - " + "; ".join(reasons) + ".")
    if not (groq_ok or gemini_ok):
        st.info("Quick mode is off - set GROQ_API_KEY (or GEMINI_API_KEY) in `.env` to transcribe recordings.")
    if not modes:
        st.warning("You can pick a file below, but nothing can transcribe it yet. Turn on one of the two modes above.")

    mode = st.radio("How should the recording be transcribed?", modes, key=f"mode_{meeting['id']}") if modes else None
    if mode == _MODE_LOCAL:
        _enroll_speakers_ui(ap)

    lang_name = st.selectbox("Language spoken", ["Auto-detect"] + list(ap.LANGUAGES), key=f"lang_{meeting['id']}")
    audio = st.file_uploader("Meeting recording", type=["wav", "mp3", "m4a", "mp4", "ogg", "flac"],
                             key=f"rec_{meeting['id']}")
    if audio:
        st.caption(f"Selected: {audio.name} ({audio.size / 1e6:.1f} MB)")

    if not st.button("🎧 Transcribe & summarise recording", type="primary", key=f"gen_rec_{meeting['id']}"):
        return
    if not audio:
        st.warning("Choose an audio file first.")
        return
    if not mode:
        st.error("No transcription engine is available - see the notes above.")
        return

    ext = audio.name.rsplit(".", 1)[-1].lower() if "." in audio.name else "wav"
    lang_code = None if lang_name == "Auto-detect" else ap.LANGUAGES[lang_name]
    status = st.empty()
    try:
        if mode == _MODE_GROQ:
            status.info("Sending the recording to Groq Whisper (a long file can take a minute) ...")
            transcript = summary_service.transcribe_audio_groq(audio.getvalue(), audio.name, lang_code)
            stats = []
        elif mode == _MODE_GEMINI:
            status.info("Sending the recording to Gemini for transcription (can take a minute) ...")
            transcript = summary_service.transcribe_audio_gemini(
                audio.getvalue(), _MIME.get(ext, "audio/mp3"), None if lang_name == "Auto-detect" else lang_name)
            stats = []
        else:
            transcript, stats, _lang = ap.transcribe_recording(audio.getvalue(), "." + ext, lang_code,
                                                               progress=lambda m: status.info(m))
        status.info("Writing the summary ...")
        ok, _rec, msg = summary_service.summarize_recording(meeting, transcript, stats, generated_by=user["id"])
    except Exception as e:
        status.empty()
        st.error(str(e))
        return
    status.empty()
    if ok:
        st.session_state["_announce_summary"] = meeting["id"]
        st.rerun()
    else:
        st.error(msg)


# ------------------------------------------------------------------ public entry points
def render_post_meeting_summary(meeting: dict, user: dict):
    """Summary section for ONE meeting (shown on the 'meeting ended' page and from the lobby tab)."""
    inject_accessibility_css()
    if not summary_service.user_took_part(meeting, user["id"]):
        st.error("Only people who took part in this meeting can see its summary.")
        return
    is_host = str(meeting.get("host_id")) == str(user["id"])
    saved = summary_service.get_saved(meeting["id"])

    if meeting.get("status") != "ended":
        st.info("🟢 This meeting is still live. The summary is available once the host ends it.")
        return

    if saved:
        _render_summary(meeting, saved, user)
        if st.session_state.get("_announce_summary") == meeting["id"]:
            st.session_state["_announce_summary"] = None
            if user.get("role") == "blind":
                speak_voice_guidance("The summary is ready. " + saved["summary"]["summary"],
                                     key_suffix=f"sum_{meeting['id']}")
        st.markdown("---")
        st.markdown("#### Create it again")

    tab_conv, tab_rec = st.tabs(["📝 From the meeting conversation", "🎧 From a recording (optional)"])
    with tab_conv:
        _tab_conversation(meeting, user, saved, is_host)
    with tab_rec:
        _tab_recording(meeting, user, is_host)


def render_summary_lobby_tab(user: dict):
    """Lobby tab: pick one of my finished meetings (or type a code) and summarise it."""
    st.markdown("### 📝 Summarize Post Meeting")
    st.caption("Get a title, summary, action items and decisions for a meeting that has finished.")
    mine = summary_service.list_meetings(user["id"])
    ended = [m for m in mine if m.get("status") == "ended"]
    live = [m for m in mine if m.get("status") != "ended"]

    chosen = None
    if ended:
        labels = [f"{m['title']} · {m['meeting_code']} · {_fmt_time(m.get('ended_at') or m.get('created_at'))}"
                  for m in ended]
        idx = st.selectbox("Your finished meetings", range(len(ended)), format_func=lambda i: labels[i],
                           key="summary_pick_meeting")
        chosen = ended[idx]
    else:
        st.info("You have no finished meetings yet. Once a host ends a meeting you took part in, it appears here.")
    if live:
        st.caption("Still live (summary available after the host ends them): "
                   + ", ".join(f"{m['title']} ({m['meeting_code']})" for m in live))

    with st.expander("Use a meeting code instead"):
        code = st.text_input("Meeting code", placeholder="AM-8F3K92", key="summary_code_input").strip()
        if code:
            m = meeting_service.refresh_meeting(code)
            if not m:
                st.error("No meeting found with that code.")
            else:
                chosen = m

    if chosen:
        st.markdown("---")
        render_post_meeting_summary(chosen, user)
