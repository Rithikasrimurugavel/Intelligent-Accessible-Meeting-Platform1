import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    MANAGER = "manager"
    NORMAL = "normal"
    BLIND = "blind"
    DEAF = "deaf"
    MUTE = "mute"
    SYSTEM = "system"


class InputType(str, Enum):
    VOICE = "voice"
    TEXT = "text"
    SIGN_LANGUAGE = "sign_language"
    SYSTEM = "system"


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    ENDED = "ended"


def _uid() -> str:
    return str(uuid.uuid4())


class UserProfile(BaseModel):
    id: str = Field(default_factory=_uid)
    email: str
    name: str
    role: UserRole
    created_at: Optional[datetime] = Field(default_factory=datetime.now)


class Meeting(BaseModel):
    id: str = Field(default_factory=_uid)
    meeting_code: str
    title: str
    host_id: str
    status: MeetingStatus = MeetingStatus.SCHEDULED
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class Participant(BaseModel):
    id: str = Field(default_factory=_uid)
    meeting_id: str
    user_id: str
    role: UserRole
    status: str = "active"
    joined_at: Optional[datetime] = Field(default_factory=datetime.now)
    left_at: Optional[datetime] = None


class Message(BaseModel):
    id: str = Field(default_factory=_uid)
    meeting_id: str
    sender_id: Optional[str] = None
    sender_name: str
    sender_role: UserRole
    input_type: InputType
    text_content: str
    original_content: Optional[str] = None
    confidence: Optional[float] = 1.0
    target: str = "all"
    status: str = "completed"
    timestamp: Optional[datetime] = Field(default_factory=datetime.now)
