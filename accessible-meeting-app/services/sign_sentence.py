"""
Turns a live stream of per-frame sign predictions into LETTERS -> WORDS -> a SENTENCE.

Why this exists: a camera image classifier answers "what is in THIS frame?" (for example the letter H).
A conversation needs the opposite: ignore flicker and empty frames, notice when a letter was held on purpose,
group letters into words, and decide when a sentence is finished. That is what this class does. It is plain
Python with an injectable clock, so it is fully unit-testable without a camera.

How a person uses it (fingerspelling):
  * Hold each letter steady for about a second.            -> letter accepted (needs N identical frames)
  * Drop your hand briefly between letters.                 -> allows the next (or the same) letter
  * Hold the same letter ~2.5 s                              -> typed twice (HELLO's LL)
  * Keep your hand down for ~2 s                             -> word finished (spelling auto-corrected)
  * Keep your hand down for ~4.5 s                           -> sentence finished and sent
"""
import difflib
import re
from typing import Any, Dict, List, Optional

from utils.config import Config
from utils.vocabulary import COMMON_WORDS, VOCAB_SET

_IGNORE = {"", "nothing", "none", "no_hand", "background", "unknown"}
_QUESTION_STARTERS = {"what", "where", "when", "why", "how", "who", "which", "can", "could", "do", "does", "did",
                      "are", "is", "will", "would", "should", "may", "was", "were", "have", "has"}
_GREETINGS = {"hello", "hi", "hey"}
_CONTRACTIONS = {"im": "I'm", "ive": "I've", "dont": "don't", "cant": "can't", "wont": "won't", "didnt": "didn't",
                 "doesnt": "doesn't", "isnt": "isn't", "arent": "aren't", "wasnt": "wasn't", "youre": "you're",
                 "thats": "that's", "whats": "what's", "lets": "let's", "theyre": "they're", "hes": "he's",
                 "shes": "she's", "couldnt": "couldn't", "wouldnt": "wouldn't", "shouldnt": "shouldn't"}


def autocorrect_word(word: str) -> str:
    """Fix single-letter recognition slips: 'helo' -> 'hello'. Unknown names are left alone."""
    w = word.lower()
    if len(w) < 3 or w in VOCAB_SET or w in _CONTRACTIONS:
        return w
    match = difflib.get_close_matches(w, COMMON_WORDS, n=1, cutoff=0.8)
    return match[0] if match else w


def suggest_words(prefix: str, limit: int = 3) -> List[str]:
    p = prefix.lower()
    if len(p) < 2:
        return []
    return [w for w in COMMON_WORDS if w.startswith(p) and w != p and "'" not in w][:limit]


def format_sentence(words: List[str]) -> str:
    """['hello', 'how', 'are', 'you'] -> 'Hello how are you?'  (capital letter, I, contractions, end mark)."""
    if not words:
        return ""
    out = []
    for w in words:
        lw = w.lower()
        out.append("I" if lw == "i" else _CONTRACTIONS.get(lw, w))
    first = out[0].lower()
    if first in _GREETINGS and len(out) > 1:          # "hello how are you" -> "Hello, how are you?"
        out[0] = out[0] + ","
        first = out[1].lower()
    text = " ".join(out)
    text = text[0].upper() + text[1:]
    text = re.sub(r"\bi\b", "I", text)
    if text[-1] not in ".?!":
        text += "?" if (first in _QUESTION_STARTERS and len(out) >= 2) else "."
    return text


class SignSentenceBuilder:
    def __init__(self, min_conf: float = None, stable_frames: int = None, repeat_hold: float = None,
                 word_pause: float = None, sentence_pause: float = None):
        self.min_conf = Config.SIGN_LIVE_MIN_CONFIDENCE if min_conf is None else min_conf
        self.stable_frames = Config.SIGN_STABLE_FRAMES if stable_frames is None else stable_frames
        self.repeat_hold = Config.SIGN_REPEAT_HOLD_SECONDS if repeat_hold is None else repeat_hold
        self.word_pause = Config.SIGN_WORD_PAUSE_SECONDS if word_pause is None else word_pause
        self.sentence_pause = Config.SIGN_SENTENCE_PAUSE_SECONDS if sentence_pause is None else sentence_pause
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self):
        self.letters: List[str] = []
        self.words: List[str] = []
        self.confs: List[float] = []
        self.candidate: Optional[str] = None
        self.candidate_conf = 0.0
        self.cand_count = 0
        self.cand_since = 0.0
        self.last_accepted: Optional[str] = None
        self.last_accept_time = 0.0
        self.released = True
        self.no_sign_since: Optional[float] = None

    # ------------------------------------------------------------------ input
    def update(self, label: Optional[str], conf: float, now: float) -> List[Dict[str, Any]]:
        """Feed ONE frame result. label=None means 'no hand / nothing recognised'. Returns finished events."""
        lab = (label or "").strip().lower()
        if lab in _IGNORE or conf < self.min_conf:
            self.candidate, self.cand_count, self.candidate_conf = None, 0, 0.0
            self.released = True
            if self.no_sign_since is None:
                self.no_sign_since = now
            return self.tick(now)

        self.no_sign_since = None
        if lab == self.candidate:
            self.cand_count += 1
            self.candidate_conf = max(self.candidate_conf, conf)
        else:
            self.candidate, self.cand_count, self.candidate_conf, self.cand_since = lab, 1, conf, now

        if self.cand_count >= self.stable_frames:
            # typing the same letter twice needs ONE continuous hold (flicker must not count)
            repeat_ok = (now - self.cand_since) >= self.repeat_hold
            if lab != self.last_accepted or self.released or repeat_ok:
                return self._accept(lab, conf, now)
        return []

    def tick(self, now: float) -> List[Dict[str, Any]]:
        """Time-based completion (call on every frame, including empty ones)."""
        events: List[Dict[str, Any]] = []
        if self.no_sign_since is None:
            return events
        idle = now - self.no_sign_since
        if self.letters and idle >= self.word_pause:
            events += self.finish_word()
        if (self.words or self.letters) and idle >= self.sentence_pause:
            events += self.finish_sentence()
        return events

    # ------------------------------------------------------------------ actions
    def _accept(self, lab: str, conf: float, now: float) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        self.last_accepted, self.last_accept_time, self.released = lab, now, False
        self.cand_since = now
        self.confs.append(conf)
        if lab in ("space", "word_end"):
            events += self.finish_word()
        elif lab in ("del", "delete", "backspace"):
            self.backspace()
        elif len(lab) == 1 and lab.isalpha():
            self.letters.append(lab.upper())
            events.append({"type": "letter", "value": lab.upper(), "confidence": conf})
        else:                                   # a model that recognises whole words
            events += self.finish_word()
            self.words.append(lab.replace("_", " "))
            events.append({"type": "word", "value": lab.replace("_", " "), "raw": lab})
        return events

    def force_letter(self, letter: str, conf: float = 1.0):
        """Add a letter immediately (used by the single-photo fallback and by tests)."""
        self.letters.append(letter.upper())
        self.confs.append(conf)

    def finish_word(self) -> List[Dict[str, Any]]:
        if not self.letters:
            return []
        raw = "".join(self.letters).lower()
        self.letters = []
        word = autocorrect_word(raw)
        self.words.append(word)
        return [{"type": "word", "value": word, "raw": raw}]

    def accept_suggestion(self, word: str):
        self.letters = []
        self.words.append(word.lower())

    def backspace(self):
        if self.letters:
            self.letters.pop()
        elif self.words:
            self.words.pop()

    def clear(self):
        self.reset()

    def finish_sentence(self) -> List[Dict[str, Any]]:
        events = self.finish_word()
        if not self.words:
            return events
        text = format_sentence(self.words)
        conf = sum(self.confs) / len(self.confs) if self.confs else 1.0
        events.append({"type": "sentence", "value": text, "confidence": round(conf, 3)})
        self.reset()
        return events

    # ------------------------------------------------------------------ view
    def preview(self) -> str:
        words = list(self.words)
        if self.letters:
            words.append("".join(self.letters).lower())
        return format_sentence(words)

    def view(self) -> Dict[str, Any]:
        return {"seeing": self.candidate, "seeing_conf": self.candidate_conf, "seeing_count": self.cand_count,
                "word": "".join(self.letters), "words": list(self.words), "preview": self.preview(),
                "suggestions": suggest_words("".join(self.letters))}
