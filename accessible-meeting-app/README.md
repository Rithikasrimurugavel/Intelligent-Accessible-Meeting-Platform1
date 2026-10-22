# 🌐 Accessible Meeting App — "Communication Without Barriers"

Inclusive online meetings for **blind**, **deaf**, **mute (sign language)**, **normal** participants and a **host**.
All input (voice, typing, sign) is converted to text, then delivered in the format each role needs
(spoken audio, large subtitles, chat).

## Quick start
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env
python tools/check_groq.py         # Linux/macOS: cp .env.example .env   -> then edit .env
python test_sanity.py          # optional offline check
streamlit run app.py
```
With **no keys** the app still runs: in-memory database and real speech-to-text through the free Google Web Speech
fallback (internet needed). Sign recognition needs a Hugging Face key (or a local model) - it never fakes a result.
Sidebar shows which mode you are in.

## 🎙️ Voice assistant (blind users) - hands-free
Turn it on with the **🎙️ Start Voice Assistant** button on the login page, the sidebar switch, `?voice=1` in the URL,
or automatically for users whose role is *blind*. Use **Chrome or Edge** (they provide continuous speech recognition),
allow the microphone, press **Enter / Space** on the big button once (browsers require one key press before a page may
speak), then talk. Press **Esc** to make the assistant stop talking.

| Where | You say |
|---|---|
| Login | "create account" (it asks name -> e-mail -> confirms by reading it back -> role), "log in" |
| Lobby | "create meeting called weekly sync", "join meeting" (then spell the code: "A M dash eight F three K nine two"), "change role", "log out" |
| Meeting | "start talking" (everything you say is sent) / "stop talking", "send message ...", "read last message", "read messages", "who is here", "meeting code", "leave meeting", "end meeting" (host) |
| Anywhere | "enable audio" / "disable audio" (spoken announcements of new messages), "help", "repeat", "cancel", "stop listening" |

While in *talk mode*, start a sentence with **"assistant"** to give a command, e.g. "assistant who is here".
New messages from other people are read aloud automatically (turn off with "disable audio").
Meeting codes no longer contain I, O, 0 or 1, because those are easy to mix up when spoken.

## 🖐️ Live sign language -> sentences (mute users)
Press **Start live camera** and fingerspell (ASL alphabet). The app reads the camera continuously:
hold each letter ~1 s -> letter; hand down ~2 s -> word (spell-checked, e.g. `helo` -> `hello`);
hand down ~4-5 s -> the finished sentence (`Hello, how are you?`) is sent to the meeting automatically
(or after you edit it, if auto-send is off). Tap a 💡 suggestion to finish a word faster.
Tuning knobs are in `.env.example` (`SIGN_*`). For speed set `SIGN_USE_LOCAL_MODEL=true` (needs `pip install transformers torch`).

**Honest limits:** the model recognises single *letters* from a still frame, so this is fingerspelling, not full
sign-language grammar; J and Z (which involve motion) are unreliable; good light and a plain background matter;
with the Hugging Face API each frame takes ~1 s, so signing is slower than with a local model.

## 📝 Summarize Post Meeting (merged from AI_Summarizer_Project)
When the host ends a meeting, everyone who took part sees a **Summarize Post Meeting** section on the "meeting ended"
page. It is also a tab in the lobby (**📝 Summarize Post Meeting**) listing all your finished meetings, so you can open it later.

* **From the meeting conversation (default, no upload):** every voice, typed and signed message is already stored with the
  speaker's name, so the app summarises that directly -> *title, summary, action items (task / owner / deadline), key decisions,
  topics, participation chart, full transcript*.
* **Engines (first that works is used, and the page says which):** Gemini (`GEMINI_API_KEY`) -> Hugging Face text model ->
  a basic offline extractive summary (no keys; it only re-uses sentences that were said and is labelled "basic, no AI").
  Owners/deadlines that nobody stated are shown as "Not specified", never guessed.
* **Accessible output:** large high-contrast cards, **🔊 read aloud** (blind users also hear the summary announced), Markdown download.
* **From a recording (optional, host only):** the notebook's pipeline - Whisper transcription + pyannote speaker separation +
  enrolled voiceprints so people get real names. Needs `pip install -r requirements-audio.txt`, `ffmpeg`, a GPU is
  strongly recommended, and a Hugging Face token that accepted the *pyannote/speaker-diarization-3.1* and *pyannote/embedding* terms.
  Voiceprints are biometric data: stored as `.npz` in `data/voiceprints/` (git-ignored), deletable from the UI.
* **Storage:** summaries are saved one-per-meeting. With Supabase run `supabase_migration_summaries.sql` (adds the table, keeps your data)
  - or `supabase_schema.sql` on a fresh project. Regenerating (host only) replaces the saved summary.
* **Tests:** `python test_summary.py` (offline).

Not carried over from the notebook: the Google Calendar tab (its `urn:ietf:wg:oauth:2.0:oob` login flow no longer works with Google)
and the Colab/ngrok launcher. The original notebook is kept as `notebooks/05_original_ai_summarizer_colab.ipynb`.

## Tests
`python test_sanity.py`, `python test_voice_and_sign.py`, `python test_summary.py` (offline). Browser components: see `tests_js/README.md`.

## Supabase
1. Create a project → SQL Editor → paste **all of `supabase_schema.sql`** → Run (it drops/recreates the 4 tables).
2. Put `SUPABASE_URL` and `SUPABASE_ANON_KEY` in `.env`.
The schema's policies allow the `anon` role because the app doesn't use Supabase Auth. That is open access —
fine for a demo, not for production.

## Hugging Face
Create a token with permission to call **Inference Providers**, set `HUGGINGFACE_API_KEY` in `.env`.
Use `notebooks/04_huggingface_api_testing.ipynb` to check that each model is actually served.
- STT: `openai/whisper-large-v3-turbo` (silent/too-quiet recordings are rejected; without a key or if HF fails,
  the free Google Web Speech fallback is used. The app never invents transcript text.)
- TTS: `facebook/mms-tts-eng` (falls back to gTTS)
- Sign camera: runs **live in the browser** (MediaPipe hand tracking on the video stream, no photos captured or
  uploaded). It recognises whole **words** in real time (10 built-in signs + words you teach it) and joins them into
  a sentence that is sent when your hands stay down ~3 s. The first start downloads the hand tracker (internet once).

## Live video meeting (Zoom-style)
Everyone joins the same video call from their role page (blind users join audio-only).
- Video and audio go **directly between browsers** (WebRTC mesh, best for up to ~6 people). The app only relays the
  small connection messages, so no media server is needed.
- **Subtitles for everyone, on top of the video:** spoken words (Chrome/Edge speech recognition in the speaker's own
  browser) and a sign-language user's signed words (hand tracking on their own camera). Finished sentences are also
  saved to the meeting conversation.
- **Camera needs a secure address:** use `http://localhost:8501` on the same computer, or an `https://` address
  (e.g. an ngrok / Cloudflare tunnel, or a deployed app) when other people join from other devices.
- Optional TURN relay for strict networks: set `TURN_URL`, `TURN_USERNAME`, `TURN_PASSWORD` in `.env`.
- Tests: `python test_video_call.py` (server side) and `node tests_js/sign_component.test.js` (browser logic).

## Structure
```
app.py                 router + sidebar
views/                 login, role_selection, meeting_room, post_meeting_summary, manager_dashboard, blind_user,
                       hearing_impaired, mute_user, normal_user
components/            accessibility, audio_recorder, speech_to_text, text_to_speech, sign_language,
                       voice_assistant/ (browser component), video_meeting/ (live video + subtitles + sign reading),
                       video_call,
                       chat, subtitles, meeting_controls, notifications
services/              summary_service, audio_pipeline (optional Whisper+pyannote), call_service (video signalling), supabase_service, huggingface_service, meeting_service, message_service, user_service
models/schemas.py   utils/ (config, logger, helpers, validation)
notebooks/             4 testing notebooks (run Jupyter from inside notebooks/)
```
> The folder is called `views/`, not `pages/` — Streamlit turns a `pages/` folder into separate auto-pages.

## Known limitations
- Video call: connection setup takes a few seconds; more than ~6 people is not supported (peer-to-peer); all
  browsers must reach the same running server (signalling is in-memory in that one process).
- Chat/subtitles poll every 3 s (not push). Browsers may block spoken guidance until the first click.
- Sign camera: 10 built-in word signs are movement/hand-shape rules (approximate); other words must be taught once
  in the "Teach the app your own word" panel. It is not a full ASL/ISL translator.
- Open RLS policies (see above).
