from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PrivacyMode(StrEnum):
    PUBLIC = "public"
    STATUS_ONLY = "status_only"
    PRIVATE = "private"


@dataclass(slots=True)
class ScheduleMember:
    group_id: str
    user_id: str
    display_name: str
    privacy: PrivacyMode
    ics_path: str
    bound_at: str


@dataclass(slots=True)
class GroupState:
    group_id: str
    unified_msg_origin: str
    members: dict[str, ScheduleMember]
    daily_report_enabled: bool = False
    auto_recall_ics_uploads: bool | None = None
    auto_recall_schedule_images: bool | None = None


@dataclass(slots=True)
class FileCandidate:
    group_id: str
    user_id: str
    display_name: str
    file_name: str
    file_url: str
    created_at: datetime
    upload_message_id: str = ""


@dataclass(frozen=True, slots=True)
class ClassOccurrence:
    title: str
    start: datetime
    end: datetime
    location: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class CurrentStatus:
    member: ScheduleMember
    active: list[ClassOccurrence]
    next_class: ClassOccurrence | None


@dataclass(frozen=True, slots=True)
class DailyReportRow:
    member: ScheduleMember
    minutes: int
    class_count: int
