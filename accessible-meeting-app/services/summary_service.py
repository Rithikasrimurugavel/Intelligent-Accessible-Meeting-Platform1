"""
Post-meeting summary.

Pipeline:   meeting messages (voice / typed / sign - already speaker-labelled text)
            -> transcript -> LLM -> {title, summary, action_items, key_decisions, topics_discussed}

Engines, tried in this order (the first that works wins; the engine used is always reported):
  1. Gemini (GEMINI_API_KEY)                 - the model the original AI_Summarizer notebook used
  2. Hugging Face chat model (HUGGINGFACE_API_KEY, HUGGINGFACE_TEXT_MODEL)
  3. Offline extractive summary              - no keys needed; plainly labelled as basic, never pretends to be AI

The summary only ever contains what was said: prompts forbid inventing owners/deadlines ("Not specified").
"""
import json
import re
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services.huggingface_service import huggingface_service
from services.supabase_service import supabase_service
from utils.config import Config
from utils.logger import logger

NOT_SPECIFIED = "Not specified"
GEMINI_INLINE_AUDIO_MAX = 14 * 1024 * 1024     # base64 inflates by 1/3; the whole request must stay under ~20 MB

SUMMARY_PROMPT = """You are an expert meeting analyst. Analyse the meeting transcript below.
Reply with ONE valid JSON object and nothing else (no markdown fences, no commentary) with exactly these keys:
- "title": short descriptive title for the meeting
- "summary": one concise paragraph with the key discussions and outcomes
- "action_items": array of objects with keys "task", "assigned_to", "deadline"
- "key_decisions": array of strings
- "topics_discussed": array of strings
Rules: use ONLY information present in the transcript. If an owner or deadline is not stated, write "Not specified".
If there are no action items or decisions, return an empty array. Participants communicate by voice, typing and sign
language, so lines may be short or fingerspelled; do not mention that unless it matters.
Write the summary in the same language as the transcript.

Meeting title given by the host: {title}

TRANSCRIPT:
'''
{transcript}
'''
"""

_STOPWORDS = set("""a an the and or but if so of to in on at for with from by is are was were be been being it this that
these those i you he she we they me him her us them my your our their not no yes ok okay just also very can could would
should will shall do does did have has had there here then than as about into over out up down what when where which who
how why all any some more most other such only own same too s t don now""".split())

_ACTION_CUES = re.compile(r"\b(will|going to|need to|needs to|must|should|please|todo|to-do|action item|follow up|"
                          r"follow-up|by (monday|tuesday|wednesday|thursday|friday|tomorrow|next week|end of))\b", re.I)
_DECISION_CUES = re.compile(r"\b(decided|decision|agreed|we will go with|let's go with|approved|final(ly)? decided|"
                            r"resolved)\b", re.I)


# --------------------------------------------------------------------------- helpers
def _parse_ts(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def extract_json_object(text: str) -> Optional[dict]:
    """Pull the first JSON object out of an LLM reply (tolerates ```json fences and chatter around it)."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(cleaned[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def normalize_summary(raw: dict, fallback_title: str) -> dict:
    """Coerce whatever the model returned into the exact shape the UI expects."""
    def as_list(v) -> list:
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def as_text(v, default="") -> str:
        t = str(v).strip() if v is not None else ""
        return t or default

    items = []
    for it in as_list(raw.get("action_items")):
        if isinstance(it, dict):
            task = as_text(it.get("task"))
            if task:
                items.append({"task": task,
                              "assigned_to": as_text(it.get("assigned_to"), NOT_SPECIFIED),
                              "deadline": as_text(it.get("deadline"), NOT_SPECIFIED)})
        elif as_text(it):
            items.append({"task": as_text(it), "assigned_to": NOT_SPECIFIED, "deadline": NOT_SPECIFIED})
    return {
        "title": as_text(raw.get("title"), fallback_title),
        "summary": as_text(raw.get("summary"), "No summary could be produced."),
        "action_items": items,
        "key_decisions": [as_text(x) for x in as_list(raw.get("key_decisions")) if as_text(x)],
        "topics_discussed": [as_text(x) for x in as_list(raw.get("topics_discussed")) if as_text(x)],
    }


# --------------------------------------------------------------------------- transcript
def build_transcript(messages: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """
    Turn stored meeting messages into 'Name (role, how): text' lines, plus statistics.
    System notices ("X joined") are left out of the transcript but their count is not used for talk time.
    """
    lines: List[str] = []
    words: Counter = Counter()
    msgs: Counter = Counter()
    via: Dict[str, Counter] = {}
    for m in messages:
        if (m.get("input_type") == "system") or (m.get("sender_role") == "system"):
            continue
        text = str(m.get("text_content") or "").strip()
        if not text:
            continue
        name = str(m.get("sender_name") or "Unknown")
        role = str(m.get("sender_role") or "normal")
        kind = str(m.get("input_type") or "text")
        lines.append(f"{name} ({role}, {kind.replace('_', ' ')}): {text}")
        words[name] += len(text.split())
        msgs[name] += 1
        via.setdefault(name, Counter())[kind] += 1
    total = sum(words.values()) or 1
    stats = {
        "speakers": [{"name": n, "words": w, "messages": msgs[n], "share": round(100 * w / total, 1),
                      "via": dict(via[n])} for n, w in words.most_common()],
        "total_words": sum(words.values()),
        "total_messages": sum(msgs.values()),
    }
    return "\n".join(lines), stats


# --------------------------------------------------------------------------- engines
_gemini_state = {"model": None}      # remembers which model last worked, shown as the engine label


def _gemini_models() -> List[str]:
    first = _gemini_state["model"] or Config.GEMINI_MODEL
    return [first] + [m for m in [Config.GEMINI_MODEL] + list(Config.GEMINI_FALLBACK_MODELS) if m != first]


def _gemini_request(model: str, parts: list, json_mode: bool, max_tokens: int = 8192, timeout: int = 90) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    cfg = {"temperature": Config.SUMMARY_TEMPERATURE, "maxOutputTokens": max_tokens}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    body = json.dumps({"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "x-goog-api-key": Config.GEMINI_API_KEY})   # key in header, not in the URL
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        err = RuntimeError(f"Gemini HTTP {e.code} ({model}): {detail or e.reason}")
        err.http_code = e.code          # type: ignore[attr-defined]
        raise err from None
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini returned no candidates ({data.get('promptFeedback', 'no feedback')})")
    out = "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or []))
    if not out.strip():
        raise RuntimeError(f"Gemini returned empty text (finishReason={cands[0].get('finishReason')})")
    return out


def _gemini_call(parts: list, json_mode: bool, **kw) -> str:
    """
    Call Gemini robustly:
      503/500/504 (busy)  -> wait and retry the same model, then move to the next model
      404 (model retired) -> next model
      anything else (bad key, quota, bad request) -> raise at once
    """
    import time
    last: Optional[Exception] = None
    for model in _gemini_models():
        for attempt in range(Config.GEMINI_RETRIES + 1):
            try:
                text = _gemini_request(model, parts, json_mode, **kw)
                if _gemini_state["model"] != model:
                    logger.info(f"Gemini model in use: {model}")
                _gemini_state["model"] = model
                return text
            except RuntimeError as e:
                last = e
                code = getattr(e, "http_code", None)
                if code in (500, 503, 504) and attempt < Config.GEMINI_RETRIES:
                    wait = Config.GEMINI_RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"{e} - retrying in {wait:.0f}s")
                    time.sleep(wait)
                    continue
                if code in (404, 500, 503, 504):
                    logger.warning(f"{e} - trying the next Gemini model")
                    break
                raise
    raise RuntimeError(f"{last}. If the model is gone, set GEMINI_MODEL in .env "
                       "(see https://ai.google.dev/gemini-api/docs/models).")


def _gemini(prompt: str) -> str:
    """Summary text -> JSON reply. Raises on any failure."""
    return _gemini_call([{"text": prompt}], json_mode=True)


TRANSCRIBE_PROMPT = """Transcribe this meeting recording exactly as spoken, in the language(s) spoken. Do not translate
and do not summarise. Separate speakers: start every turn on a new line as "Speaker 1: ...", "Speaker 2: ..." (keep the
same number for the same voice; if people say their names, use the names). Output only the transcript.{lang}"""


def transcribe_audio_gemini(audio_bytes: bytes, mime: str, language_name: Optional[str] = None) -> str:
    """Transcribe an uploaded recording with Gemini (no local models needed). Small files only (inline upload)."""
    import base64
    if not Config.is_gemini_configured():
        raise RuntimeError("GEMINI_API_KEY is not set.")
    if len(audio_bytes) > GEMINI_INLINE_AUDIO_MAX:
        raise RuntimeError(f"This file is {len(audio_bytes) / 1e6:.1f} MB; the Gemini quick mode accepts up to "
                           f"{GEMINI_INLINE_AUDIO_MAX / 1e6:.0f} MB. Compress it first (e.g. mono 32 kbps mp3) or "
                           "use the Whisper + pyannote mode.")
    prompt = TRANSCRIBE_PROMPT.format(lang=f" The language is {language_name}." if language_name else "")
    parts = [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio_bytes).decode()}}]
    return _gemini_call(parts, json_mode=False, max_tokens=32768, timeout=600).strip()


def _groq_post(url: str, *, json_body: Optional[dict] = None, files: Optional[dict] = None,
               data: Optional[dict] = None, timeout: int = 60, what: str = "Groq"):
    """POST to Groq with `requests`. Retries connection resets / 429 / 5xx; raises RuntimeError with a clear reason."""
    import time
    import requests
    headers = {"Authorization": f"Bearer {Config.GROQ_API_KEY}", "User-Agent": "accessible-meeting-app/1.0"}
    last: Optional[Exception] = None
    for attempt in range(4):
        try:
            r = requests.post(url, headers=headers, json=json_body, files=files, data=data, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            last = RuntimeError(f"{what}: could not reach api.groq.com ({type(e).__name__}). Check your internet, "
                                "VPN / proxy / firewall / antivirus (HTTPS scanning), or try another network or a "
                                "mobile hotspot.")
            logger.warning(f"{last} [{e}]")
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise last from None
        if r.status_code == 200:
            return r.json()
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            detail = r.text[:200]
        last = RuntimeError(f"{what} HTTP {r.status_code}: {detail or r.reason}")
        if r.status_code in (429, 500, 502, 503) and attempt < 3:
            try:
                wait = min(20.0, float(r.headers.get("retry-after", 3 * (attempt + 1))))
            except ValueError:
                wait = 3.0
            logger.warning(f"{last} - retrying in {wait:.0f}s")
            time.sleep(wait)
            continue
        raise last
    raise last or RuntimeError(f"{what} failed")


def _groq(prompt: str, json_mode: bool = True, max_tokens: int = 2048) -> str:
    """Chat call to Groq (OpenAI-compatible)."""
    body = {"model": Config.GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": Config.SUMMARY_TEMPERATURE, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = _groq_post("https://api.groq.com/openai/v1/chat/completions", json_body=body,
                      what=f"Groq ({Config.GROQ_MODEL})")
    out = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if not out.strip():
        raise RuntimeError("Groq returned an empty reply")
    return out


GROQ_NOTES_PROMPT = """This is part {i} of {n} of a meeting transcript. Write concise notes (at most 200 words) of the
topics discussed, decisions made, and action items (who / what / by when). Use the same language as the transcript.
Output the notes only.

{chunk}"""


def _split_chunks(text: str, size: int, max_chunks: int = 8) -> List[str]:
    """Split on line boundaries into pieces of at most ~size characters."""
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:                      # one giant line: hard-split it
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) > size and cur:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        chunks.append(cur)
    return chunks[:max_chunks]


def _groq_summary(transcript: str, title: str) -> Tuple[str, bool]:
    """Summarise with Groq. Long transcripts are first condensed part by part so nothing is cut off."""
    limit = Config.GROQ_MAX_TRANSCRIPT_CHARS
    condensed = False
    if len(transcript) > limit:
        parts = _split_chunks(transcript, limit)
        notes = [_groq(GROQ_NOTES_PROMPT.format(i=i, n=len(parts), chunk=c), json_mode=False, max_tokens=600)
                 for i, c in enumerate(parts, 1)]
        transcript = "(Condensed notes of a long meeting, in order)\n\n" + "\n\n".join(notes)
        condensed = True
    return _groq(SUMMARY_PROMPT.format(title=title or "(none)", transcript=transcript)), condensed


def _shrink_audio(audio_bytes: bytes, ext: str, max_bytes: int) -> Tuple[bytes, str]:
    """Re-encode to mono 16 kHz 32 kbps mp3 (about 14 MB per hour) when the file is over Groq's upload limit."""
    import shutil, subprocess, tempfile, os
    if not shutil.which("ffmpeg"):
        raise RuntimeError(f"This file is {len(audio_bytes) / 1e6:.1f} MB (limit {max_bytes / 1e6:.0f} MB) and ffmpeg "
                           "is not installed to shrink it. Install ffmpeg or upload a smaller / compressed file.")
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in." + ext), os.path.join(d, "out.mp3")
        with open(src, "wb") as f:
            f.write(audio_bytes)
        r = subprocess.run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", dst],
                           capture_output=True, timeout=1800)
        if r.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("ffmpeg could not read this audio file.")
        data = open(dst, "rb").read()
    if len(data) > max_bytes:
        raise RuntimeError(f"Even after compressing, the audio is {len(data) / 1e6:.1f} MB (limit "
                           f"{max_bytes / 1e6:.0f} MB). Split the recording into shorter parts.")
    return data, "mp3"


_AUDIO_MIME = {"mp3": "audio/mpeg", "mpeg": "audio/mpeg", "mpga": "audio/mpeg", "wav": "audio/wav",
               "m4a": "audio/mp4", "mp4": "audio/mp4", "ogg": "audio/ogg", "flac": "audio/flac", "webm": "audio/webm"}


def transcribe_audio_groq(audio_bytes: bytes, filename: str, language_code: Optional[str] = None) -> str:
    """Speech-to-text with Groq's hosted Whisper. No speaker names (Whisper does not tell voices apart)."""
    if not Config.is_groq_configured():
        raise RuntimeError("GROQ_API_KEY is not set.")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
    max_bytes = int(Config.GROQ_STT_MAX_MB * 1024 * 1024)
    if len(audio_bytes) > max_bytes:
        audio_bytes, ext = _shrink_audio(audio_bytes, ext, max_bytes)
    fields = {"model": Config.GROQ_STT_MODEL, "response_format": "json", "temperature": "0"}
    if language_code:
        fields["language"] = language_code
    data = _groq_post("https://api.groq.com/openai/v1/audio/transcriptions", data=fields, timeout=600,
                      files={"file": (f"audio.{ext}", audio_bytes, _AUDIO_MIME.get(ext, "application/octet-stream"))},
                      what=f"Groq speech-to-text ({Config.GROQ_STT_MODEL})")
    text = (data.get("text") or "").strip()
    if not text:
        raise RuntimeError("Groq heard no speech in this recording.")
    return text


def _hf_chat(prompt: str) -> str:
    client = huggingface_service.client
    if client is None:
        raise RuntimeError("Hugging Face key not active")
    out = client.chat_completion(model=Config.HUGGINGFACE_TEXT_MODEL, max_tokens=2048,
                                 temperature=Config.SUMMARY_TEMPERATURE,
                                 messages=[{"role": "user", "content": prompt}])
    return out.choices[0].message.content or ""


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip().split()) >= 3]


def offline_summary(transcript: str, title: str) -> dict:
    """
    Keyword-based extractive summary. It only re-uses sentences that were actually said. Basic by design -
    it is the safety net when no AI key works, and the UI labels it as such.
    """
    # strip the "Name (role, how): " prefix but remember who said what
    spoken: List[Tuple[str, str]] = []
    for line in transcript.splitlines():
        m = re.match(r"^(.*?)(?: \([^)]*\))?: (.*)$", line)
        who, text = (m.group(1), m.group(2)) if m else ("Unknown", line)
        for s in _sentences(text) or ([text] if text.strip() else []):
            spoken.append((who, s))
    if not spoken:
        return normalize_summary({"summary": "The meeting conversation was empty, so there is nothing to summarise."},
                                 title)

    freq = Counter(w for _, s in spoken for w in re.findall(r"[a-zA-Z']{3,}", s.lower()) if w not in _STOPWORDS)
    scored = []
    for i, (_, s) in enumerate(spoken):
        toks = [w for w in re.findall(r"[a-zA-Z']{3,}", s.lower()) if w not in _STOPWORDS]
        scored.append((sum(freq[w] for w in toks) / (len(toks) ** 0.5 or 1), i))
    top = sorted(i for _, i in sorted(scored, reverse=True)[:min(4, len(spoken))])
    summary = " ".join(spoken[i][1] for i in top)

    actions, decisions = [], []
    for who, s in spoken:
        if _DECISION_CUES.search(s):
            decisions.append(s)
        elif _ACTION_CUES.search(s):
            actions.append({"task": s, "assigned_to": who if re.search(r"\b(i|i'll|i will)\b", s, re.I)
                            else NOT_SPECIFIED, "deadline": NOT_SPECIFIED})
    topics = [w for w, _ in freq.most_common(6)]
    return normalize_summary({"summary": summary, "action_items": actions[:8], "key_decisions": decisions[:8],
                              "topics_discussed": topics}, title)


def summarize_text(transcript: str, title: str) -> Tuple[dict, str, List[str]]:
    """Return (summary, engine_label, warnings). Tries Groq -> Gemini -> Hugging Face -> offline."""
    warnings: List[str] = []
    clipped = transcript
    if len(clipped) > Config.SUMMARY_MAX_TRANSCRIPT_CHARS:
        clipped = clipped[:Config.SUMMARY_MAX_TRANSCRIPT_CHARS]
        warnings.append(f"The transcript was longer than {Config.SUMMARY_MAX_TRANSCRIPT_CHARS:,} characters; "
                        "only the first part was summarised.")
    prompt = SUMMARY_PROMPT.format(title=title or "(none)", transcript=clipped)

    engines = []
    if Config.is_groq_configured():
        engines.append((f"Groq ({Config.GROQ_MODEL})", lambda _p: _groq_summary(clipped, title)))
    if Config.is_gemini_configured():
        engines.append(("Gemini", _gemini))
    if huggingface_service.is_live:
        engines.append((f"Hugging Face ({Config.HUGGINGFACE_TEXT_MODEL})", _hf_chat))
    for label, fn in engines:
        try:
            reply = fn(prompt)
            if isinstance(reply, tuple):                       # Groq: (text, was_condensed)
                reply, condensed = reply
                if condensed:
                    warnings.append("This is a long meeting, so it was condensed in parts before the final summary.")
            obj = extract_json_object(reply)
            if obj is None:
                raise ValueError("the reply was not valid JSON")
            if label == "Gemini":
                label = f"Gemini ({_gemini_state['model']})"
            return normalize_summary(obj, title), label, warnings
        except Exception as e:
            logger.warning(f"Summary engine {label} failed: {e}")
            warnings.append(f"{label} failed: {e}")
    if not engines:
        warnings.append("No AI key is configured (set GROQ_API_KEY, GEMINI_API_KEY or HUGGINGFACE_API_KEY), so a basic offline "
                        "summary was used.")
    return offline_summary(transcript, title), "Offline extractive (basic, no AI)", warnings


# --------------------------------------------------------------------------- public API
class SummaryService:
    transcribe_audio_gemini = staticmethod(transcribe_audio_gemini)
    transcribe_audio_groq = staticmethod(transcribe_audio_groq)

    @staticmethod
    def get_saved(meeting_id: str) -> Optional[Dict[str, Any]]:
        try:
            return supabase_service.get_summary(meeting_id)
        except Exception as e:
            logger.error(f"get_summary error: {e}")
            return None

    @staticmethod
    def list_meetings(user_id: str) -> List[Dict[str, Any]]:
        try:
            return supabase_service.list_user_meetings(user_id)
        except Exception as e:
            logger.error(f"list_user_meetings error: {e}")
            return []

    @staticmethod
    def user_took_part(meeting: Dict[str, Any], user_id: str) -> bool:
        if str(meeting.get("host_id")) == str(user_id):
            return True
        return any(str(m["id"]) == str(meeting["id"]) for m in SummaryService.list_meetings(user_id))

    @staticmethod
    def _meeting_facts(meeting: Dict[str, Any]) -> Dict[str, Any]:
        start, end = _parse_ts(meeting.get("started_at")), _parse_ts(meeting.get("ended_at"))
        minutes = round((end - start).total_seconds() / 60, 1) if start and end else None
        parts = supabase_service.get_participants(meeting["id"]) if meeting.get("id") else []
        return {"duration_minutes": minutes, "participants_now": len(parts)}

    @classmethod
    def _keep_existing_ai_summary(cls, meeting, engine: str, warnings: List[str]) -> Optional[str]:
        """If the AI engines failed and a real AI summary is already saved, keep it instead of replacing it."""
        if not engine.startswith("Offline"):
            return None
        old = cls.get_saved(meeting["id"])
        if old and not str(old.get("engine", "")).startswith("Offline"):
            return ("The AI engines are busy right now, so your existing AI summary was kept. Try again in a minute. "
                    + " | ".join(warnings))
        return None

    @classmethod
    def summarize_meeting(cls, meeting: Dict[str, Any], generated_by: Optional[str] = None
                          ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Summarise the stored conversation of a meeting and save the result. Returns (ok, record, message)."""
        try:
            messages = supabase_service.get_messages(meeting["id"])
            transcript, stats = build_transcript(messages)
            if not transcript.strip():
                return False, None, "This meeting has no conversation to summarise (no voice, typed or sign messages)."
            summary, engine, warnings = summarize_text(transcript, meeting.get("title", ""))
            blocked = cls._keep_existing_ai_summary(meeting, engine, warnings)
            if blocked:
                return False, None, blocked
            summary["full_transcript"] = transcript
            summary["stats"] = {**stats, **cls._meeting_facts(meeting)}
            summary["warnings"] = warnings
            record = supabase_service.save_summary(meeting["id"], summary, "conversation", generated_by, engine)
            return True, record, f"Summary created with {engine}."
        except Exception as e:
            logger.error(f"summarize_meeting error: {e}")
            return False, None, f"Could not create the summary: {e}"

    @classmethod
    def summarize_recording(cls, meeting: Dict[str, Any], transcript: str, speaker_stats: Optional[list],
                            generated_by: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Summarise a transcript produced from an uploaded recording (see services/audio_pipeline.py)."""
        if not (transcript or "").strip():
            return False, None, "The recording produced no transcript."
        try:
            summary, engine, warnings = summarize_text(transcript, meeting.get("title", ""))
            blocked = cls._keep_existing_ai_summary(meeting, engine, warnings)
            if blocked:
                return False, None, blocked
            summary["full_transcript"] = transcript
            total = sum(s["seconds"] for s in (speaker_stats or [])) or 1
            summary["stats"] = {
                "speakers": [{"name": s["name"], "seconds": round(s["seconds"], 1),
                              "share": round(100 * s["seconds"] / total, 1)} for s in (speaker_stats or [])],
                **cls._meeting_facts(meeting)}
            summary["warnings"] = warnings
            record = supabase_service.save_summary(meeting["id"], summary, "recording", generated_by, engine)
            return True, record, f"Summary created with {engine}."
        except Exception as e:
            logger.error(f"summarize_recording error: {e}")
            return False, None, f"Could not create the summary: {e}"

    @staticmethod
    def to_markdown(meeting: Dict[str, Any], record: Dict[str, Any]) -> str:
        s = record["summary"]
        out = [f"# {s['title']}", f"*Meeting code: {meeting.get('meeting_code', '')} · "
               f"Summary engine: {record.get('engine', '')}*", "", "## Summary", s["summary"], ""]
        out += ["## Action items"] + ([f"- **{a['task']}** — owner: {a['assigned_to']}, deadline: {a['deadline']}"
                                       for a in s["action_items"]] or ["- None recorded"]) + [""]
        out += ["## Key decisions"] + ([f"- {d}" for d in s["key_decisions"]] or ["- None recorded"]) + [""]
        out += ["## Topics discussed"] + ([f"- {t}" for t in s["topics_discussed"]] or ["- None recorded"]) + [""]
        out += ["## Full transcript", "", s.get("full_transcript", "")]
        return "\n".join(out)

    @staticmethod
    def to_spoken_text(record: Dict[str, Any]) -> str:
        """Plain sentences for text-to-speech (no markdown, short enough to listen to)."""
        s = record["summary"]
        parts = [f"Meeting summary. {s['title']}.", s["summary"]]
        if s["key_decisions"]:
            parts.append("Key decisions. " + " ".join(f"{i}. {d}" for i, d in enumerate(s["key_decisions"], 1)))
        if s["action_items"]:
            parts.append("Action items. " + " ".join(
                f"{i}. {a['task']}" + ("" if a["assigned_to"] == NOT_SPECIFIED else f", assigned to {a['assigned_to']}")
                + ("" if a["deadline"] == NOT_SPECIFIED else f", due {a['deadline']}")
                for i, a in enumerate(s["action_items"], 1)))
        return " ".join(parts)


summary_service = SummaryService()
