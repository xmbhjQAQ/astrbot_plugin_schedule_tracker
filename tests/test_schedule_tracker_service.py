import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from astrbot_plugin_schedule_tracker.ics_parser import CalendarParseError
from astrbot_plugin_schedule_tracker.models import ClassOccurrence
from astrbot_plugin_schedule_tracker.models import (
    GroupState,
    PrivacyMode,
    ScheduleMember,
)
from astrbot_plugin_schedule_tracker.service import (
    ScheduleService,
    merged_minutes,
    week_bounds,
)
from astrbot_plugin_schedule_tracker.storage import ScheduleStorage


TZ = ZoneInfo("Asia/Shanghai")


def test_merged_minutes_does_not_double_count_overlaps():
    occurrences = [
        ClassOccurrence(
            "A",
            datetime(2026, 5, 14, 8, 0, tzinfo=TZ),
            datetime(2026, 5, 14, 10, 0, tzinfo=TZ),
        ),
        ClassOccurrence(
            "B",
            datetime(2026, 5, 14, 9, 30, tzinfo=TZ),
            datetime(2026, 5, 14, 11, 0, tzinfo=TZ),
        ),
        ClassOccurrence(
            "C",
            datetime(2026, 5, 14, 13, 0, tzinfo=TZ),
            datetime(2026, 5, 14, 14, 0, tzinfo=TZ),
        ),
    ]

    assert merged_minutes(occurrences) == 240


def test_week_bounds_starts_on_monday():
    start, end = week_bounds(datetime(2026, 5, 14, 12, 0, tzinfo=TZ))

    assert start == datetime(2026, 5, 11, 0, 0, tzinfo=TZ)
    assert end == datetime(2026, 5, 18, 0, 0, tzinfo=TZ)


def test_storage_load_groups_ignores_corrupt_state_file(tmp_path):
    storage = ScheduleStorage(tmp_path)
    storage.state_path.write_text("{not json", encoding="utf-8")

    assert storage.load_groups() == {}


def test_storage_load_groups_skips_invalid_member(tmp_path):
    storage = ScheduleStorage(tmp_path)
    storage.state_path.write_text(
        json.dumps(
            {
                "groups": {
                    "100": {
                        "unified_msg_origin": "origin",
                        "members": {
                            "bad": {"privacy": "broken"},
                            "200": {
                                "display_name": "Alice",
                                "privacy": PrivacyMode.PUBLIC.value,
                                "ics_path": "alice.ics",
                                "bound_at": "2026-05-14T08:00:00+08:00",
                            },
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    groups = storage.load_groups()

    assert set(groups["100"].members) == {"200"}
    assert groups["100"].members["200"].display_name == "Alice"


class _DailyReportParser:
    def occurrences_between(self, ics_path, start, end):
        if ics_path == "broken.ics":
            raise CalendarParseError("broken file")
        return [
            ClassOccurrence(
                "Math",
                datetime(2026, 5, 14, 8, 0, tzinfo=TZ),
                datetime(2026, 5, 14, 9, 0, tzinfo=TZ),
            )
        ]


def test_daily_report_skips_broken_member_schedule():
    group = GroupState(
        group_id="100",
        unified_msg_origin="origin",
        members={
            "good": ScheduleMember(
                group_id="100",
                user_id="good",
                display_name="Good",
                privacy=PrivacyMode.PUBLIC,
                ics_path="good.ics",
                bound_at="",
            ),
            "bad": ScheduleMember(
                group_id="100",
                user_id="bad",
                display_name="Bad",
                privacy=PrivacyMode.PUBLIC,
                ics_path="broken.ics",
                bound_at="",
            ),
        },
    )
    service = ScheduleService(_DailyReportParser(), TZ)

    rows = service.daily_report(group, date(2026, 5, 14))

    assert [row.member.user_id for row in rows] == ["good"]
    assert rows[0].minutes == 60
