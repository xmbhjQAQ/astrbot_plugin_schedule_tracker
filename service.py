"""Pure schedule calculations used by command handlers and daily reports."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from astrbot.api import logger

from .ics_parser import CalendarDependencyError, CalendarParseError
from .ics_parser import IcsScheduleParser
from .models import (
    ClassOccurrence,
    CurrentStatus,
    DailyReportRow,
    GroupState,
    ScheduleMember,
)


def day_bounds(day: date, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the inclusive start and exclusive end for a local calendar day."""

    start = datetime.combine(day, time.min, tzinfo=timezone)
    return start, start + timedelta(days=1)


def week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return the Monday-to-Monday window containing ``now``."""

    local = now.astimezone(now.tzinfo)
    monday = local.date() - timedelta(days=local.weekday())
    start = datetime.combine(monday, time.min, tzinfo=local.tzinfo)
    return start, start + timedelta(days=7)


def merged_minutes(occurrences: list[ClassOccurrence]) -> int:
    """Count occupied minutes without double-counting overlapping events."""

    if not occurrences:
        return 0
    intervals = sorted((item.start, item.end) for item in occurrences)
    merged: list[list[datetime]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
            continue
        if end > merged[-1][1]:
            merged[-1][1] = end
    return int(sum((end - start).total_seconds() for start, end in merged) // 60)


class ScheduleService:
    """Read parsed ICS occurrences and shape them for plugin features."""

    def __init__(self, parser: IcsScheduleParser, timezone: ZoneInfo) -> None:
        self.parser = parser
        self.timezone = timezone

    def current_status(self, member: ScheduleMember, now: datetime) -> CurrentStatus:
        """Return active classes and the next upcoming class for one member."""

        start = now - timedelta(hours=12)
        end = now + timedelta(days=14)
        occurrences = self.parser.occurrences_between(member.ics_path, start, end)
        active = [item for item in occurrences if item.start <= now < item.end]
        next_class = next((item for item in occurrences if item.start > now), None)
        return CurrentStatus(member=member, active=active, next_class=next_class)

    def week_schedule(
        self,
        member: ScheduleMember,
        now: datetime,
    ) -> tuple[datetime, list[ClassOccurrence]]:
        """Return this week's occurrences for a member."""

        start, end = week_bounds(now)
        return start, self.parser.occurrences_between(member.ics_path, start, end)

    def daily_report(self, group: GroupState, day: date) -> list[DailyReportRow]:
        """Rank non-empty member schedules by total occupied minutes."""

        start, end = day_bounds(day, self.timezone)
        rows: list[DailyReportRow] = []
        for member in group.members.values():
            try:
                occurrences = self.parser.occurrences_between(
                    member.ics_path, start, end
                )
            except (CalendarDependencyError, CalendarParseError, OSError) as exc:
                # 日报是批处理任务，单个成员的课表损坏时跳过该成员。
                logger.warning(
                    "跳过无法读取的课表日报成员 group=%s user=%s: %s",
                    group.group_id,
                    member.user_id,
                    exc,
                )
                continue
            minutes = merged_minutes(occurrences)
            if minutes > 0:
                rows.append(
                    DailyReportRow(
                        member=member,
                        minutes=minutes,
                        class_count=len(occurrences),
                    )
                )
        return sorted(rows, key=lambda row: (-row.minutes, row.member.display_name))
