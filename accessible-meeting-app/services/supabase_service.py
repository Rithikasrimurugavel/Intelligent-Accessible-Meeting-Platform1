import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.config import Config
from utils.logger import logger

try:
    from supabase import create_client
    HAS_SUPABASE_LIB = True
except ImportError:
    HAS_SUPABASE_LIB = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseService:
    """
    Supabase (PostgreSQL) store.
    If Supabase is NOT configured, a process-wide in-memory store is used (shared by all browser sessions).
    If Supabase IS configured, errors are raised (not silently swallowed) so callers can show them.
    """

    # shared in-memory fallback
    _users: Dict[str, Dict[str, Any]] = {}
    _meetings: Dict[str, Dict[str, Any]] = {}       # keyed by meeting_code
    _participants: List[Dict[str, Any]] = []
    _messages: List[Dict[str, Any]] = []
    _summaries: Dict[str, Dict[str, Any]] = {}      # keyed by meeting_id

    def __init__(self):
        self.client = None
        self.use_supabase = False
        if HAS_SUPABASE_LIB and Config.is_supabase_configured():
            try:
                self.client = create_client(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY)
                self.use_supabase = True
                logger.info("Connected to Supabase.")
            except Exception as e:
                logger.warning(f"Supabase connection failed ({e}); using in-memory store.")
        else:
            logger.info("Supabase not configured; using in-memory store.")

    # ----------------------------------------------------------- users
    def create_user_profile(self, user_id: str, email: str, name: str, role: str) -> Dict[str, Any]:
        data = {"id": str(user_id), "email": email, "name": name, "role": role, "created_at": _now()}
        if self.use_supabase:
            res = self.client.table("profiles").upsert(data).execute()
            return res.data[0] if res.data else data
        self._users[data["id"]] = data.copy()
        return data

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        if self.use_supabase:
            res = self.client.table("profiles").select("*").eq("id", str(user_id)).execute()
            return res.data[0] if res.data else None
        u = self._users.get(str(user_id))
        return u.copy() if u else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        email = email.strip().lower()
        if self.use_supabase:
            res = self.client.table("profiles").select("*").eq("email", email).limit(1).execute()
            return res.data[0] if res.data else None
        for u in self._users.values():
            if u["email"] == email:
                return u.copy()
        return None

    # --------------------------------------------------------- meetings
    def create_meeting(self, meeting_code: str, title: str, host_id: str) -> Dict[str, Any]:
        now = _now()
        data = {"id": str(uuid.uuid4()), "meeting_code": meeting_code.strip().upper(), "title": title,
                "host_id": str(host_id), "status": "active", "created_at": now, "started_at": now, "ended_at": None}
        if self.use_supabase:
            res = self.client.table("meetings").insert(data).execute()
            return res.data[0] if res.data else data
        self._meetings[data["meeting_code"]] = data.copy()
        return data

    def get_meeting_by_code(self, meeting_code: str) -> Optional[Dict[str, Any]]:
        code = meeting_code.strip().upper()
        if self.use_supabase:
            res = self.client.table("meetings").select("*").eq("meeting_code", code).execute()
            return res.data[0] if res.data else None
        m = self._meetings.get(code)
        return m.copy() if m else None

    def end_meeting(self, meeting_id: str) -> bool:
        mid, now = str(meeting_id), _now()
        if self.use_supabase:
            res = self.client.table("meetings").update({"status": "ended", "ended_at": now}).eq("id", mid).execute()
            return bool(res.data)
        for m in self._meetings.values():
            if m["id"] == mid:
                m["status"], m["ended_at"] = "ended", now
                return True
        return False

    def get_meeting_by_id(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        mid = str(meeting_id)
        if self.use_supabase:
            res = self.client.table("meetings").select("*").eq("id", mid).execute()
            return res.data[0] if res.data else None
        for m in self._meetings.values():
            if m["id"] == mid:
                return m.copy()
        return None

    def list_user_meetings(self, user_id: str) -> List[Dict[str, Any]]:
        """Meetings the user hosted or took part in, newest first."""
        uid = str(user_id)
        if self.use_supabase:
            ids = {r["meeting_id"] for r in (self.client.table("participants").select("meeting_id")
                                              .eq("user_id", uid).execute().data or [])}
            hosted = self.client.table("meetings").select("*").eq("host_id", uid).execute().data or []
            ids |= {m["id"] for m in hosted}
            if not ids:
                return []
            rows = self.client.table("meetings").select("*").in_("id", list(ids)).execute().data or []
        else:
            ids = {p["meeting_id"] for p in self._participants if p["user_id"] == uid}
            rows = [m.copy() for m in self._meetings.values() if m["id"] in ids or str(m["host_id"]) == uid]
        return sorted(rows, key=lambda m: str(m.get("created_at") or ""), reverse=True)

    # ------------------------------------------------------ participants
    def join_meeting(self, meeting_id: str, user_id: str, role: str) -> Dict[str, Any]:
        data = {"id": str(uuid.uuid4()), "meeting_id": str(meeting_id), "user_id": str(user_id), "role": role,
                "status": "active", "joined_at": _now(), "left_at": None}
        if self.use_supabase:
            res = self.client.table("participants").upsert(data, on_conflict="meeting_id,user_id").execute()
            return res.data[0] if res.data else data
        SupabaseService._participants = [p for p in self._participants
                                         if not (p["meeting_id"] == data["meeting_id"] and p["user_id"] == data["user_id"])]
        self._participants.append(data.copy())
        return data

    def get_participants(self, meeting_id: str) -> List[Dict[str, Any]]:
        mid = str(meeting_id)
        if self.use_supabase:
            res = (self.client.table("participants").select("*").eq("meeting_id", mid)
                   .eq("status", "active").execute())
            out = []
            for p in res.data or []:
                prof = self.get_user_profile(p["user_id"])
                p["name"] = prof.get("name", "Participant") if prof else "Participant"
                out.append(p)
            return out
        out = []
        for p in self._participants:
            if p["meeting_id"] == mid and p["status"] == "active":
                c = p.copy()
                c["name"] = self._users.get(p["user_id"], {}).get("name", "Participant")
                out.append(c)
        return out

    def leave_meeting(self, meeting_id: str, user_id: str) -> bool:
        mid, uid, now = str(meeting_id), str(user_id), _now()
        if self.use_supabase:
            res = (self.client.table("participants").update({"status": "left", "left_at": now})
                   .eq("meeting_id", mid).eq("user_id", uid).execute())
            return bool(res.data)
        for p in self._participants:
            if p["meeting_id"] == mid and p["user_id"] == uid:
                p["status"], p["left_at"] = "left", now
                return True
        return False

    # ---------------------------------------------------------- messages
    def send_message(self, meeting_id: str, sender_id: Optional[str], sender_name: str, sender_role: str,
                     input_type: str, text_content: str, original_content: Optional[str] = None,
                     confidence: Optional[float] = 1.0) -> Dict[str, Any]:
        data = {"id": str(uuid.uuid4()), "meeting_id": str(meeting_id),
                "sender_id": str(sender_id) if sender_id else None,
                "sender_name": sender_name, "sender_role": sender_role, "input_type": input_type,
                "text_content": text_content, "original_content": original_content or text_content,
                "confidence": float(confidence) if confidence is not None else None,
                "target": "all", "status": "completed", "timestamp": _now()}
        if self.use_supabase:
            res = self.client.table("messages").insert(data).execute()
            return res.data[0] if res.data else data
        self._messages.append(data.copy())
        return data

    def get_messages(self, meeting_id: str) -> List[Dict[str, Any]]:
        mid = str(meeting_id)
        if self.use_supabase:
            res = (self.client.table("messages").select("*").eq("meeting_id", mid)
                   .order("timestamp", desc=False).execute())
            return res.data or []
        return [m.copy() for m in self._messages if m["meeting_id"] == mid]

    # ---------------------------------------------------------- summaries
    def save_summary(self, meeting_id: str, summary: Dict[str, Any], source: str, generated_by: Optional[str],
                     engine: str) -> Dict[str, Any]:
        """One saved summary per meeting (regenerating replaces it). `summary` is stored as JSON."""
        data = {"meeting_id": str(meeting_id), "summary": summary, "source": source,
                "engine": engine, "generated_by": str(generated_by) if generated_by else None,
                "generated_at": _now()}
        if self.use_supabase:
            res = self.client.table("meeting_summaries").upsert(data, on_conflict="meeting_id").execute()
            return res.data[0] if res.data else data
        self._summaries[data["meeting_id"]] = dict(data)
        return data

    def get_summary(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        mid = str(meeting_id)
        if self.use_supabase:
            res = self.client.table("meeting_summaries").select("*").eq("meeting_id", mid).execute()
            return res.data[0] if res.data else None
        s = self._summaries.get(mid)
        return dict(s) if s else None


supabase_service = SupabaseService()
