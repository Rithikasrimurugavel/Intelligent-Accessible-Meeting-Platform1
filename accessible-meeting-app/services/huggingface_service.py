import io
import math
import struct
import wave
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image

from utils.config import Config
from utils.logger import logger

try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False

# Phrases Whisper-style models "hallucinate" when audio is silent / too quiet / noisy.
_HALLUCINATIONS = (
    "thanks for watching", "thank you for watching", "thanks for attending",
    "thank you for attending", "thanks for attend", "thank you for joining",
    "thanks for joining", "thank you so much for watching", "please subscribe",
    "subtitles by", "amara.org", "thank you.", "thanks.", "you", "bye.", "bye-bye.",
)
_MIN_RMS = 150          # below this (16-bit scale 0..32767) the recording is basically silence
_MIN_SECONDS = 0.4

try:
    import transformers  # noqa: F401  (optional: only needed for SIGN_USE_LOCAL_MODEL=true)
    HAS_TRANSFORMERS = True
except Exception:
    HAS_TRANSFORMERS = False

try:
    from huggingface_hub import InferenceClient
    HAS_HF_HUB = True
except ImportError:
    HAS_HF_HUB = False


def _attr(obj: Any, name: str, default=None):
    """Read a field from either a dataclass-like object or a dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class HuggingFaceService:
    """
    STT / TTS / sign recognition through huggingface_hub.InferenceClient.

    - API key configured  -> real model calls. Failures are reported honestly (no fake output).
    - No API key          -> free Google Web Speech fallback for STT; sign recognition is OFF (never fake output).
    - TTS always falls back to gTTS (a real engine) if the HF call fails.
    """

    def __init__(self):
        self.stt_model = Config.HUGGINGFACE_STT_MODEL
        self.tts_model = Config.HUGGINGFACE_TTS_MODEL
        self.sign_model = Config.HUGGINGFACE_SIGN_MODEL
        self.client = None
        if Config.is_huggingface_configured() and HAS_HF_HUB:
            self.client = InferenceClient(token=Config.HUGGINGFACE_API_KEY, timeout=60)

    @property
    def is_live(self) -> bool:
        return self.client is not None

    def diagnose(self) -> list:
        """Plain-language reasons why the Hugging Face key is not active (empty list = all good)."""
        import os
        from utils.config import ENV_FILE
        key = Config.HUGGINGFACE_API_KEY
        problems = []
        if not HAS_HF_HUB:
            problems.append("The package 'huggingface_hub' is not installed. Run:  pip install huggingface-hub")
        if not key:
            if ENV_FILE:
                problems.append(f"Found your .env file ({ENV_FILE}) but HUGGINGFACE_API_KEY is empty or missing in it. "
                                "The line must look like:  HUGGINGFACE_API_KEY=hf_...  (no spaces, no quotes).")
            else:
                problems.append("No .env file was found. Create a file named exactly '.env' (not '.env.txt' - on "
                                "Windows turn on 'File name extensions') in the same folder as app.py.")
                if os.path.exists(".env.txt"):
                    problems.append("I can see a file called '.env.txt' - rename it to '.env'.")
        elif not key.startswith("hf_"):
            problems.append("The token should start with 'hf_'. Check you copied the whole token.")
        elif not Config.is_huggingface_configured():
            problems.append("The token still looks like the placeholder text from .env.example. Paste your real token.")
        return problems

    @property
    def sign_available(self) -> bool:
        """True when sign recognition can really run (HF key, or a local model)."""
        return self.client is not None or (Config.SIGN_USE_LOCAL_MODEL and HAS_TRANSFORMERS)

    _local_sign_pipe = None

    def _classify_local(self, pil_img):
        """Run the sign model on THIS computer (fast, offline). Needs: pip install transformers torch."""
        if HuggingFaceService._local_sign_pipe is None:
            from transformers import pipeline
            HuggingFaceService._local_sign_pipe = pipeline("image-classification", model=self.sign_model)
        return HuggingFaceService._local_sign_pipe(pil_img, top_k=3)

    # ------------------------------------------------------------------ STT
    @staticmethod
    def _analyze_wav(audio_bytes: bytes) -> Optional[Dict[str, float]]:
        """Return {'rms','seconds','rate'} for a PCM WAV, or None if it is not a readable PCM WAV."""
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                n, width, ch, rate = wf.getnframes(), wf.getsampwidth(), wf.getnchannels(), wf.getframerate()
                frames = wf.readframes(n)
            if width != 2 or n == 0:
                return None
            samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
            if ch > 1:                       # use first channel only
                samples = samples[::ch]
            rms = math.sqrt(sum(x * x for x in samples) / max(len(samples), 1))
            return {"rms": rms, "seconds": n / float(rate), "rate": rate}
        except Exception:
            return None

    @staticmethod
    def _looks_like_hallucination(text: str) -> bool:
        t = text.strip().lower()
        return any(t == h or t.rstrip(".! ") == h.rstrip(".! ") for h in _HALLUCINATIONS)

    def _stt_huggingface(self, audio_bytes: bytes) -> str:
        out = self.client.automatic_speech_recognition(audio_bytes, model=self.stt_model)
        return (_attr(out, "text", "") or "").strip()

    @staticmethod
    def _stt_google_free(audio_bytes: bytes) -> str:
        """Free Google Web Speech API (no key, needs internet). Needs a PCM WAV."""
        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
            audio = recognizer.record(source)
        try:
            return (recognizer.recognize_google(audio, language="en-US") or "").strip()
        except sr.UnknownValueError:
            return ""

    def speech_to_text(self, audio_bytes: bytes, content_type: str = "audio/wav") -> Dict[str, Any]:
        """
        Real transcription only - NEVER returns made-up text.
        Order: Hugging Face Whisper (if key) -> free Google Web Speech (if SpeechRecognition installed).
        """
        if not audio_bytes:
            return {"success": False, "error": "Empty audio data received."}

        # 1) Reject silent / too-short recordings BEFORE calling a model (this is what makes
        #    Whisper invent phrases like "Thanks for attending this meeting").
        info = self._analyze_wav(audio_bytes)
        if info:
            logger.info(f"STT audio: {info['seconds']:.2f}s, rms={info['rms']:.0f}, rate={info['rate']}Hz")
            if info["seconds"] < _MIN_SECONDS:
                return {"success": False, "error": "Recording is too short. Speak for at least a second."}
            if info["rms"] < _MIN_RMS:
                return {"success": False,
                        "error": "Recording is silent / too quiet. Check your microphone and speak closer to it."}

        errors = []

        # 2) Hugging Face Whisper
        if self.client:
            try:
                text = self._stt_huggingface(audio_bytes)
                if text and not self._looks_like_hallucination(text):
                    logger.info(f"HF STT ok: '{text}'")
                    return {"success": True, "text": text, "confidence": None, "simulated": False,
                            "note": f"Transcribed by {self.stt_model}."}
                errors.append("Hugging Face returned empty/suspicious text" + (f" ('{text}')" if text else ""))
            except Exception as e:
                logger.error(f"HF STT failed: {e}")
                errors.append(f"Hugging Face failed: {e}")

        # 3) Free Google Web Speech fallback (works with no API key)
        if HAS_SR:
            try:
                text = self._stt_google_free(audio_bytes)
                if text:
                    logger.info(f"Google STT ok: '{text}'")
                    return {"success": True, "text": text, "confidence": None, "simulated": False,
                            "note": "Transcribed by Google Web Speech (free fallback)."}
                errors.append("Google Web Speech could not understand the audio")
            except Exception as e:
                logger.error(f"Google STT failed: {e}")
                errors.append(f"Google Web Speech failed (internet needed): {e}")
        elif not self.client:
            return {"success": False,
                    "error": "No speech engine available. Set HUGGINGFACE_API_KEY in .env, or run "
                             "'pip install SpeechRecognition' for the free fallback."}

        return {"success": False,
                "error": "No speech was recognised. " + " | ".join(errors) if errors
                else "No speech was recognised."}

    # ------------------------------------------------------------------ TTS
    def text_to_speech(self, text: str) -> Tuple[bool, Optional[bytes], str]:
        if not text or not text.strip():
            return False, None, "Text content is empty."
        clean = text.strip()

        if self.client:
            try:
                audio = self.client.text_to_speech(clean, model=self.tts_model)
                if audio and len(audio) > 100:
                    return True, bytes(audio), f"Generated via Hugging Face ({self.tts_model})."
            except Exception as e:
                logger.warning(f"HF TTS failed, trying gTTS: {e}")

        if HAS_GTTS:
            try:
                fp = io.BytesIO()
                gTTS(text=clean, lang="en").write_to_fp(fp)
                return True, fp.getvalue(), "Generated via gTTS fallback (MP3)."
            except Exception as e:
                logger.error(f"gTTS fallback error: {e}")

        return False, None, "Text-to-Speech is currently unavailable (no HF key and gTTS failed/offline)."

    # ----------------------------------------------------------- Sign language
    @staticmethod
    def _to_pil(image_data: Any) -> Optional[Image.Image]:
        try:
            if isinstance(image_data, (bytes, bytearray)):
                return Image.open(io.BytesIO(image_data)).convert("RGB")
            if isinstance(image_data, np.ndarray):
                return Image.fromarray(image_data).convert("RGB")
            if isinstance(image_data, Image.Image):
                return image_data.convert("RGB")
        except Exception as e:
            logger.warning(f"Could not decode image: {e}")
        return None

    def detect_sign_language(self, image_data: Any) -> Dict[str, Any]:
        """Classify ONE frame. Never invents a result: without a model it returns an honest error."""
        pil_img = self._to_pil(image_data)
        if pil_img is None:
            return {"success": False, "sign": None, "confidence": 0.0, "error": "Invalid or unreadable image."}

        if not self.sign_available:
            return {"success": False, "sign": None, "confidence": 0.0, "unavailable": True,
                    "error": "Sign recognition needs a Hugging Face API key (HUGGINGFACE_API_KEY in .env) "
                             "or a local model (SIGN_USE_LOCAL_MODEL=true and pip install transformers torch)."}
        try:
            if Config.SIGN_USE_LOCAL_MODEL and HAS_TRANSFORMERS:
                preds = self._classify_local(pil_img)
                used = f"{self.sign_model} (local)"
            else:
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=90)
                preds = self.client.image_classification(buf.getvalue(), model=self.sign_model)
                used = self.sign_model
            if not preds:
                return {"success": False, "sign": None, "confidence": 0.0, "error": "Model returned no prediction."}
            top = max(preds, key=lambda p: float(_attr(p, "score", 0.0)))
            return {"success": True, "sign": str(_attr(top, "label", "")).upper(),
                    "confidence": float(_attr(top, "score", 0.0)), "model_used": used, "simulated": False}
        except Exception as e:
            logger.error(f"Sign model failed: {e}")
            return {"success": False, "sign": None, "confidence": 0.0,
                    "error": f"Sign model request failed ({self.sign_model}): {e}"}

    # ----------------------------------------------------- sentence tidy-up
    def refine_sentence(self, text: str) -> str:
        """
        Optional: let an LLM fix spelling/punctuation of a signed sentence. It may NOT add or change meaning;
        anything suspicious (too long, multi-line, empty) is discarded and the original text is used.
        """
        original = (text or "").strip()
        if not original or not self.client:
            return original
        try:
            out = self.client.chat_completion(
                model=Config.HUGGINGFACE_TEXT_MODEL, max_tokens=80, temperature=0.1,
                messages=[
                    {"role": "system", "content":
                     "You fix a short sentence that was typed by fingerspelling. Correct only spelling, capital "
                     "letters and punctuation. Do NOT add, remove or change the meaning of any words. "
                     "Reply with the corrected sentence only."},
                    {"role": "user", "content": original}])
            fixed = (out.choices[0].message.content or "").strip().strip('"')
            if fixed and "\n" not in fixed and len(fixed) <= len(original) * 2 + 10:
                return fixed
        except Exception as e:
            logger.warning(f"Sentence refinement skipped: {e}")
        return original


huggingface_service = HuggingFaceService()
