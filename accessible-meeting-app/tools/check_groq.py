"""Run:  python tools/check_groq.py   - finds out WHICH step to Groq fails (network, key, upload)."""
import os, sys, io, wave, struct, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from utils.config import Config

def step(name, fn):
    try:
        print(f"[ OK ] {name}: {fn()}")
        return True
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {str(e)[:300]}")
        return False

if not Config.is_groq_configured():
    sys.exit("GROQ_API_KEY is missing in .env")
H = {"Authorization": f"Bearer {Config.GROQ_API_KEY}"}
print("Proxy env:", {k: v for k, v in os.environ.items() if "proxy" in k.lower()} or "none")

step("1. Reach api.groq.com (GET models)", lambda: f"HTTP {requests.get('https://api.groq.com/openai/v1/models', headers=H, timeout=20).status_code} (401 = bad key)")
step("2. Small POST (chat)", lambda: requests.post("https://api.groq.com/openai/v1/chat/completions", headers=H, timeout=30,
     json={"model": Config.GROQ_MODEL, "messages": [{"role": "user", "content": "Say hi"}], "max_tokens": 5}).json()["choices"][0]["message"]["content"])

def tiny_audio():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i / 10))) for i in range(16000)))
    r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=H, timeout=60,
                      data={"model": Config.GROQ_STT_MODEL}, files={"file": ("t.wav", buf.getvalue(), "audio/wav")})
    return f"HTTP {r.status_code} {r.text[:120]}"
step("3. Tiny audio upload (32 KB)", tiny_audio)

def big_upload():
    r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=H, timeout=120,
                      data={"model": Config.GROQ_STT_MODEL}, files={"file": ("t.wav", b"\0" * 2_000_000, "audio/wav")})
    return f"HTTP {r.status_code} (400 is fine here - fake audio; the point is that the 2 MB upload was not reset)"
step("4. 2 MB upload", big_upload)
