"""
Signalling for the live video meeting (WebRTC mesh).

Video and audio travel directly between browsers (peer-to-peer). This service only carries the tiny "who is here"
and "offer / answer" messages that let two browsers find each other. It is a process-wide in-memory store, so every
browser connected to the same running Streamlit server shares it.
"""
import threading
import time
from typing import Any, Dict, List, Optional

PEER_TTL_SECONDS = 8        # a browser that has not checked in for this long has left
SIGNAL_TTL_SECONDS = 30     # signals older than this are dropped
MAX_SIGNAL_BYTES = 120_000  # an SDP is ~5-15 KB; anything bigger is not a real offer/answer
MAX_PEERS = 8


class CallService:
    def __init__(self):
        self._lock = threading.Lock()
        self._rooms: Dict[str, Dict[str, Any]] = {}

    def _room(self, room: str) -> Dict[str, Any]:
        return self._rooms.setdefault(room, {"peers": {}, "sigs": [], "seq": 0})

    def _expire(self, r: Dict[str, Any], now: float):
        r["peers"] = {s: p for s, p in r["peers"].items() if now - p["ts"] <= PEER_TTL_SECONDS}
        r["sigs"] = [g for g in r["sigs"] if now - g["ts"] <= SIGNAL_TTL_SECONDS]

    # ------------------------------------------------------------ presence
    def heartbeat(self, room: str, sid: str, uid: str, name: str, role: str) -> bool:
        """Register / refresh a browser session. Returns False if the room is full."""
        now = time.time()
        with self._lock:
            r = self._room(room)
            self._expire(r, now)
            if sid not in r["peers"] and len(r["peers"]) >= MAX_PEERS:
                return False
            r["peers"][sid] = {"sid": sid, "uid": str(uid), "name": str(name)[:60], "role": str(role)[:20], "ts": now}
            return True

    def leave(self, room: str, sid: Optional[str] = None, uid: Optional[str] = None):
        with self._lock:
            r = self._rooms.get(room)
            if not r:
                return
            r["peers"] = {s: p for s, p in r["peers"].items()
                          if not ((sid and s == sid) or (uid and p["uid"] == str(uid)))}
            if not r["peers"]:
                self._rooms.pop(room, None)

    def peers(self, room: str, exclude_sid: Optional[str] = None) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            r = self._rooms.get(room)
            if not r:
                return []
            self._expire(r, now)
            return [{k: p[k] for k in ("sid", "uid", "name", "role")}
                    for s, p in r["peers"].items() if s != exclude_sid]

    # ------------------------------------------------------------ signals
    def push(self, room: str, frm: str, to: str, data: Any) -> bool:
        try:
            import json
            if len(json.dumps(data)) > MAX_SIGNAL_BYTES:
                return False
        except (TypeError, ValueError):
            return False
        now = time.time()
        with self._lock:
            r = self._room(room)
            if frm not in r["peers"] or to not in r["peers"]:      # both ends must be present
                return False
            r["seq"] += 1
            r["sigs"].append({"seq": r["seq"], "frm": frm, "to": to, "data": data, "ts": now})
            return True

    def inbox(self, room: str, sid: str) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            r = self._rooms.get(room)
            if not r:
                return []
            self._expire(r, now)
            return [{"seq": g["seq"], "frm": g["frm"], "data": g["data"]} for g in r["sigs"] if g["to"] == sid]


call_service = CallService()
