from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import ClassOccurrence


class CalendarDependencyError(RuntimeError):
    pass


class CalendarParseError(ValueError):
    pass


def _coerce_datetime(value: datetime | date, timezone: ZoneInfo, end: bool = False) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)
    return datetime.combine(value, time.max if end else time.min, tzinfo=timezone)


class IcsScheduleParser:
    def __init__(self, timezone: ZoneInfo) -> None:
        self.timezone = timezone

    def occurrences_between(
        self,
        ics_path: str | Path,
        start: datetime,
        end: datetime,
    ) -> list[ClassOccurrence]:
        try:
            from icalendar import Calendar
            import recurring_ical_events
        except ImportError as exc:
            raise CalendarDependencyError(
                "缺少 ICS 解析依赖，请在插件目录安装 requirements.txt。"
            ) from exc

        path = Path(ics_path)
        try:
            calendar = Calendar.from_ical(path.read_bytes())
            events = recurring_ical_events.of(calendar).between(start, end)
        except Exception as exc:
            raise CalendarParseError(f"ICS 文件解析失败: {exc}") from exc

        occurrences: list[ClassOccurrence] = []
        for event in events:
            dtstart = event.get("DTSTART")
            dtend = event.get("DTEND")
            if not dtstart:
                continue
            start_dt = _coerce_datetime(dtstart.dt, self.timezone)
            if dtend:
                end_dt = _coerce_datetime(dtend.dt, self.timezone, end=True)
            else:
                end_dt = start_dt
            if end_dt <= start_dt:
                continue
            occurrences.append(
                ClassOccurrence(
                    title=str(event.get("SUMMARY") or "未命名课程"),
                    start=start_dt,
                    end=end_dt,
                    location=str(event.get("LOCATION") or ""),
                    description=str(event.get("DESCRIPTION") or ""),
                )
            )
        return sorted(occurrences, key=lambda item: (item.start, item.end, item.title))
