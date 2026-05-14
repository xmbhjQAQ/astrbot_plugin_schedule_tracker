import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from astrbot_plugin_schedule_tracker.binding import ScheduleBinder
from astrbot_plugin_schedule_tracker.ics_parser import CalendarParseError
from astrbot_plugin_schedule_tracker.models import (
    FileCandidate,
    PrivacyMode,
    ScheduleMember,
)


TZ = ZoneInfo("Asia/Shanghai")


class _Event:
    unified_msg_origin = "origin"

    def __init__(self, group_id: str = "100", user_id: str = "200") -> None:
        self.group_id = group_id
        self.user_id = user_id

    def get_group_id(self) -> str:
        return self.group_id

    def get_sender_id(self) -> str:
        return self.user_id

    def get_sender_name(self) -> str:
        return "Alice"


class _Component:
    def __init__(self, path: str = "alice.ics", error: Exception | None = None) -> None:
        self.path = path
        self.error = error

    async def get_file(self) -> str:
        if self.error:
            raise self.error
        return self.path


class _Parser:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.paths: list[str] = []

    def occurrences_between(self, path, start, end):
        self.paths.append(str(path))
        if self.error:
            raise self.error
        return []


class _Storage:
    def __init__(self, error: OSError | None = None) -> None:
        self.error = error
        self.source_path = ""

    def bind_schedule(self, groups, **kwargs):
        if self.error:
            raise self.error
        self.source_path = kwargs["source_path"]
        return ScheduleMember(
            group_id=kwargs["group_id"],
            user_id=kwargs["user_id"],
            display_name=kwargs["display_name"],
            privacy=PrivacyMode.PUBLIC,
            ics_path=kwargs["source_path"],
            bound_at="",
        )


def _candidate() -> FileCandidate:
    return FileCandidate(
        group_id="100",
        user_id="200",
        display_name="Alice",
        file_name="alice.ics",
        file_url="local-file-id",
        created_at=datetime(2026, 5, 14, 8, 0, tzinfo=TZ),
    )


def test_bind_candidate_saves_valid_schedule():
    parser = _Parser()
    storage = _Storage()
    binder = ScheduleBinder(parser=parser, storage=storage, groups={}, timezone=TZ)

    result = asyncio.run(
        binder.bind_candidate(_Event(), _candidate(), _Component("ok.ics"))
    )

    assert result.member is not None
    assert result.message == "Alice 的课表已绑定，默认公开。"
    assert parser.paths == ["ok.ics"]
    assert storage.source_path == "ok.ics"


def test_bind_candidate_reports_download_failure():
    binder = ScheduleBinder(
        parser=_Parser(),
        storage=_Storage(),
        groups={},
        timezone=TZ,
    )

    result = asyncio.run(
        binder.bind_candidate(
            _Event(), _candidate(), _Component(error=RuntimeError("network"))
        )
    )

    assert result.member is None
    assert result.message == "ICS 文件下载失败，请稍后重试或重新上传。"


def test_bind_candidate_reports_parse_failure():
    binder = ScheduleBinder(
        parser=_Parser(CalendarParseError("bad ics")),
        storage=_Storage(),
        groups={},
        timezone=TZ,
    )

    result = asyncio.run(
        binder.bind_candidate(_Event(), _candidate(), _Component("bad.ics"))
    )

    assert result.member is None
    assert result.message == "这个 ICS 文件解析失败，请检查文件格式。"


def test_bind_candidate_reports_storage_failure():
    binder = ScheduleBinder(
        parser=_Parser(),
        storage=_Storage(OSError("disk full")),
        groups={},
        timezone=TZ,
    )

    result = asyncio.run(
        binder.bind_candidate(_Event(), _candidate(), _Component("ok.ics"))
    )

    assert result.member is None
    assert result.message == "课表保存失败，请稍后再试。"
