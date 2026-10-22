"""
OPTIONAL: turn an uploaded meeting RECORDING into a speaker-labelled transcript.
Ported from the AI_Summarizer_Project notebook (Whisper + pyannote speaker diarization + voiceprint enrollment).

Needs the heavy extras (see requirements-audio.txt), ffmpeg on PATH, a GPU is strongly recommended, and a Hugging Face
token that has accepted the terms of  pyannote/speaker-diarization-3.1  and  pyannote/embedding.
Nothing here is imported unless the "From a recording" tab is used, so the normal app never needs these packages.

Differences from the notebook (all deliberate fixes):
  * voiceprints are saved as .npz (numpy) instead of pickle - unpickling a file from disk can run arbitrary code
  * fp16 is only used when CUDA is available (the notebook's fp16=True fails/warns on CPU)
  * words are assigned to a speaker by their midpoint and consecutive words are merged into one turn
  * the audio is converted once with ffmpeg (no pydub dependency)
"""
import os
import re
import subprocess
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from utils.config import Config
from utils.logger import logger

LANGUAGES = {"English": "en", "Tamil": "ta", "Hindi": "hi", "Malayalam": "ml", "Kannada": "kn",
             "Telugu": "te", "Bengali": "bn", "Marathi": "mr"}


# ----------------------------------------------------------------- availability
def missing_dependencies() -> List[str]:
    """Names of the optional packages that are not installed (empty list = ready)."""
    missing = []
    for mod, pip_name in (("torch", "torch"), ("whisper", "openai-whisper"), ("pyannote.audio", "pyannote.audio")):
        try:
            __import__(mod)
        except Exception:
            missing.append(pip_name)
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        missing.append("ffmpeg (system program)")
    return missing


# ----------------------------------------------------------------- pure logic (unit-tested)
def assign_words_to_turns(words: List[Dict[str, Any]], turns: List[Tuple[float, float, str]]
                          ) -> List[Tuple[str, str]]:
    """
    words: [{'word', 'start', 'end'}]   turns: [(start, end, speaker_label)]
    Returns [(speaker_label, text)] with consecutive words by the same speaker merged.
    A word goes to the turn that contains its midpoint; if none does (pauses between turns) to the nearest turn.
    """
    if not words or not turns:
        return []
    out: List[Tuple[str, str]] = []
    for w in sorted(words, key=lambda x: x["start"]):
        mid = (w["start"] + w["end"]) / 2
        label = None
        for s, e, lab in turns:
            if s <= mid < e:
                label = lab
                break
        if label is None:
            label = min(turns, key=lambda t: min(abs(mid - t[0]), abs(mid - t[1])))[2]
        text = w["word"]
        if out and out[-1][0] == label:
            out[-1] = (label, out[-1][1] + text)
        else:
            out.append((label, text))
    return [(lab, re.sub(r"\s+", " ", t).strip()) for lab, t in out if t.strip()]


def talk_seconds(turns: List[Tuple[float, float, str]], label_to_name: Dict[str, str]) -> List[Dict[str, Any]]:
    totals: Dict[str, float] = {}
    for s, e, lab in turns:
        name = label_to_name.get(lab, lab)
        totals[name] = totals.get(name, 0.0) + max(0.0, e - s)
    return [{"name": n, "seconds": sec} for n, sec in sorted(totals.items(), key=lambda kv: -kv[1])]


def match_voiceprint(embedding: np.ndarray, enrolled: List[Dict[str, Any]],
                     threshold: float) -> Optional[str]:
    """Closest enrolled speaker by cosine distance, or None if nobody is close enough."""
    best_name, best_dist = None, 2.0
    e = np.asarray(embedding, dtype=float).ravel()
    for sp in enrolled:
        v = np.asarray(sp["voiceprint"], dtype=float).ravel()
        denom = (np.linalg.norm(e) * np.linalg.norm(v)) or 1.0
        dist = 1.0 - float(np.dot(e, v) / denom)
        if dist < best_dist:
            best_name, best_dist = sp["name"], dist
    return best_name if best_dist < threshold else None


# ----------------------------------------------------------------- voiceprint storage
def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_ -]", "", name).strip()[:60] or "speaker"


def list_speakers() -> List[Dict[str, Any]]:
    d = Config.VOICEPRINT_DIR
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".npz"):
            path = os.path.join(d, fn)
            try:
                with np.load(path, allow_pickle=False) as z:
                    out.append({"name": str(z["name"]), "voiceprint": z["voiceprint"], "path": path})
            except Exception as e:
                logger.warning(f"Skipping unreadable voiceprint {fn}: {e}")
    return out


def delete_speaker(path: str) -> bool:
    try:
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(Config.VOICEPRINT_DIR):
            os.remove(path)
            return True
    except Exception as e:
        logger.warning(f"delete_speaker failed: {e}")
    return False


# ----------------------------------------------------------------- heavy models (lazy)
_models: Dict[str, Any] = {}


def _device():
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _load_models():
    if _models:
        return _models
    if not Config.is_huggingface_configured():
        raise RuntimeError("HUGGINGFACE_API_KEY is required to download the pyannote models.")
    import whisper
    from pyannote.audio import Inference, Model, Pipeline
    dev = _device()
    logger.info(f"Loading Whisper '{Config.WHISPER_MODEL}' and pyannote on {dev} ...")
    _models["whisper"] = whisper.load_model(Config.WHISPER_MODEL, device=dev)
    tok = Config.HUGGINGFACE_API_KEY
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=tok)
        emb = Model.from_pretrained("pyannote/embedding", use_auth_token=tok)
    except TypeError:                       # newer pyannote renamed the argument
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=tok)
        emb = Model.from_pretrained("pyannote/embedding", token=tok)
    if pipe is None or emb is None:
        raise RuntimeError("pyannote models could not be loaded. Accept the model terms on huggingface.co "
                           "(pyannote/speaker-diarization-3.1 and pyannote/embedding) with the same account as your token.")
    _models["diarization"] = pipe.to(dev)
    _models["embedding"] = Inference(emb, window="whole", device=dev)
    return _models


def _to_wav(data: bytes, suffix: str) -> str:
    """Convert uploaded audio to a 16 kHz mono wav in a temp file (caller deletes it)."""
    src = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".bin")
    try:
        src.write(data)
        src.close()
        dst = os.path.join(tempfile.gettempdir(), f"meeting_{uuid.uuid4().hex}.wav")
        r = subprocess.run(["ffmpeg", "-y", "-i", src.name, "-ac", "1", "-ar", "16000", dst],
                           capture_output=True)
        if r.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("ffmpeg could not read this audio file: "
                               + r.stderr.decode("utf-8", "ignore")[-300:])
        return dst
    finally:
        os.remove(src.name)


def enroll_speaker(name: str, audio_bytes: bytes, suffix: str = ".wav") -> str:
    """Store a voiceprint (use 15-30 s of ONE clear voice). Returns the saved path."""
    m = _load_models()
    wav = _to_wav(audio_bytes, suffix)
    try:
        vp = np.asarray(m["embedding"](wav), dtype=float).ravel()
    finally:
        os.remove(wav)
    os.makedirs(Config.VOICEPRINT_DIR, exist_ok=True)
    path = os.path.join(Config.VOICEPRINT_DIR, f"{_safe(name)}_{uuid.uuid4().hex[:8]}.npz")
    np.savez(path, name=np.array(name.strip()), voiceprint=vp)
    return path


# ----------------------------------------------------------------- main entry point
def transcribe_recording(audio_bytes: bytes, suffix: str, language_code: Optional[str],
                         progress=lambda msg: None) -> Tuple[str, List[Dict[str, Any]], str]:
    """
    Returns (transcript 'Name: text' lines, talk-time stats [{'name','seconds'}], detected_language_code).
    language_code=None -> auto-detect. Raises RuntimeError with a readable message on failure.
    """
    import torch
    import whisper
    from pyannote.core import Segment

    m = _load_models()
    wav = _to_wav(audio_bytes, suffix)
    try:
        progress("Detecting language ...")
        audio = whisper.load_audio(wav)
        mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(audio)).to(m["whisper"].device)
        _, probs = m["whisper"].detect_language(mel)
        detected = max(probs, key=probs.get)
        if language_code and detected != language_code:
            raise RuntimeError(f"You selected '{language_code}' but the audio sounds like '{detected}'. "
                               "Choose Auto-detect or the matching language.")
        lang = language_code or detected

        progress("Finding who spoke when (this is the slow part) ...")
        diar = m["diarization"](wav)
        turns = [(t.start, t.end, lab) for t, _, lab in diar.itertracks(yield_label=True)]
        if not turns:
            raise RuntimeError("No speech was found in this recording.")

        progress("Matching voices to enrolled speakers ...")
        enrolled = list_speakers()
        label_to_name: Dict[str, str] = {}
        generic = 1
        for lab in sorted({l for _, _, l in turns}):
            name = None
            if enrolled:
                longest = max((t for t in turns if t[2] == lab), key=lambda t: t[1] - t[0])
                seg = Segment(longest[0], min(longest[1], longest[0] + 30))
                emb = m["embedding"].crop(wav, seg)
                name = match_voiceprint(emb, enrolled, Config.SPEAKER_MATCH_DISTANCE)
            if not name:
                name, generic = f"Speaker {generic}", generic + 1
            label_to_name[lab] = name

        progress("Transcribing ...")
        result = m["whisper"].transcribe(wav, language=lang, word_timestamps=True,
                                         fp16=bool(torch.cuda.is_available()))
        words = [w for seg in result.get("segments", []) for w in seg.get("words", [])]
        parts = assign_words_to_turns(words, turns)
        if not parts:
            raise RuntimeError("The recording could not be transcribed (no words detected).")
        transcript = "\n".join(f"{label_to_name.get(lab, lab)}: {text}" for lab, text in parts)
        return transcript, talk_seconds(turns, label_to_name), lang
    finally:
        if os.path.exists(wav):
            os.remove(wav)
