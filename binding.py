"""Bind uploaded ICS files to group members.

The plugin command layer should stay focused on AstrBot routing and replies. This
module owns the I/O-heavy binding workflow: resolve a platform file to a local
path, validate that the ICS can be parsed, and persist the copied schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import File

from .ics_parser import CalendarDependencyError, CalendarParseError, IcsScheduleParser
from .models import FileCandidate, GroupState, ScheduleMember
from .storage import ScheduleStorage


@dataclass(frozen=True, slots=True)
class BindResult:
    """User-facing result returned to the command handler."""

    message: str
    member: ScheduleMember | None = None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Internal result for the platform file resolution step."""

    path: str = ""
    error_message: str = ""


class ScheduleBinder:
    """Coordinates the bind workflow without knowing how replies are sent."""

    def __init__(
        self,
        *,
        parser: IcsScheduleParser,
        storage: ScheduleStorage,
        groups: dict[str, GroupState],
        timezone: ZoneInfo,
    ) -> None:
        self.parser = parser
        self.storage = storage
        self.groups = groups
        self.timezone = timezone

    async def bind_candidate(
        self,
        event: AstrMessageEvent,
        candidate: FileCandidate,
        component: File | None,
    ) -> BindResult:
        """Validate and persist one remembered ICS upload."""

        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not group_id or not user_id:
            return BindResult("只能在群聊中绑定自己的课表。")

        download = await self._download_ics(candidate, component)
        if download.error_message:
            return BindResult(download.error_message)
        if not download.path:
            return BindResult("没有拿到可下载的 ICS 文件。")

        now = datetime.now(self.timezone)
        try:
            # Parse a short future window before saving so broken calendars never
            # become the active schedule for that member.
            self.parser.occurrences_between(download.path, now, now + timedelta(days=7))
        except CalendarDependencyError as exc:
            return BindResult(str(exc))
        except CalendarParseError:
            return BindResult("这个 ICS 文件解析失败，请检查文件格式。")

        try:
            member = self.storage.bind_schedule(
                self.groups,
                group_id=group_id,
                unified_msg_origin=event.unified_msg_origin,
                user_id=user_id,
                display_name=event.get_sender_name() or user_id,
                source_path=download.path,
                timezone=self.timezone,
            )
        except OSError as exc:
            logger.exception("保存课表 ICS 文件失败: %s", exc)
            return BindResult("课表保存失败，请稍后再试。")
        return BindResult(f"{member.display_name} 的课表已绑定，默认公开。", member)

    async def _download_ics(
        self,
        candidate: FileCandidate,
        component: File | None,
    ) -> DownloadResult:
        """Resolve the AstrBot file component or remembered file reference."""

        try:
            if component is not None:
                file_path = await component.get_file()
                if file_path:
                    return DownloadResult(path=file_path)

            # 转发文件可能只留下 URL 或平台文件引用，需要重新构造 File 取本地路径。
            if candidate.file_url.startswith(("http://", "https://")):
                temp_file = File(name=candidate.file_name, url=candidate.file_url)
            else:
                temp_file = File(name=candidate.file_name, file=candidate.file_url)
            return DownloadResult(path=await temp_file.get_file())
        except Exception as exc:
            logger.exception("课表 ICS 文件下载失败: %s", exc)
            return DownloadResult(
                error_message="ICS 文件下载失败，请稍后重试或重新上传。"
            )
