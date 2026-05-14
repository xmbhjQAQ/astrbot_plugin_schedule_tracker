from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from html import escape
from math import ceil, floor

from .models import ClassOccurrence, CurrentStatus, DailyReportRow, PrivacyMode, ScheduleMember


DAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
STATUS_WIDTH = 760
WEEK_WIDTH = 1120
REPORT_WIDTH = 820
MIN_GRID_MINUTES = 180


STYLE = """
<style>
* {
  box-sizing: border-box;
}
html,
body {
  margin: 0;
  width: max-content;
  min-width: 0;
  height: max-content;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  color: #1f2937;
  background: transparent;
}
.render-frame {
  overflow: hidden;
  padding: 22px;
  background:
    radial-gradient(circle at 12% 0%, rgba(75, 119, 190, 0.14), transparent 32%),
    radial-gradient(circle at 88% 10%, rgba(45, 160, 115, 0.12), transparent 30%),
    linear-gradient(145deg, #f7f9fc 0%, #eef3f8 100%);
}
.surface {
  width: 100%;
  border-radius: 22px;
  padding: 24px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(210, 220, 232, 0.86);
  box-shadow:
    0 24px 60px rgba(31, 41, 55, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  margin-bottom: 20px;
}
.identity {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.avatar {
  flex: 0 0 auto;
  width: 58px;
  height: 58px;
  border-radius: 18px;
  object-fit: cover;
  background: linear-gradient(145deg, #dfe7f2, #ffffff);
  border: 2px solid rgba(255, 255, 255, 0.9);
  box-shadow:
    0 12px 24px rgba(31, 41, 55, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
.avatar.small {
  width: 44px;
  height: 44px;
  border-radius: 14px;
}
.avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #526174;
  font-weight: 800;
  font-size: 18px;
}
.title-wrap {
  min-width: 0;
}
.title {
  min-width: 0;
  font-size: 28px;
  line-height: 1.16;
  font-weight: 900;
  color: #172033;
  overflow-wrap: anywhere;
}
.subtitle {
  margin-top: 7px;
  font-size: 14px;
  line-height: 1.45;
  color: #697789;
  overflow-wrap: anywhere;
}
.pill {
  flex: 0 0 auto;
  padding: 9px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid #d8e2ee;
  color: #415168;
  font-size: 14px;
  font-weight: 800;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.hero {
  padding: 18px;
  border-radius: 18px;
  background: linear-gradient(145deg, #ffffff, #f4f7fb);
  border: 1px solid #dbe5f0;
  box-shadow:
    10px 14px 32px rgba(31, 41, 55, 0.08),
    -8px -8px 22px rgba(255, 255, 255, 0.92);
}
.status {
  font-size: 25px;
  line-height: 1.28;
  font-weight: 900;
  color: #142033;
  overflow-wrap: anywhere;
}
.course {
  margin-top: 14px;
  padding: 16px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid #d9e5f1;
  border-left: 6px solid #4f83c4;
  box-shadow: 0 10px 24px rgba(56, 73, 94, 0.08);
}
.course-name {
  font-size: 20px;
  line-height: 1.32;
  font-weight: 900;
  color: #203049;
  overflow-wrap: anywhere;
}
.muted {
  color: #647184;
  font-size: 14px;
  line-height: 1.48;
  margin-top: 5px;
  overflow-wrap: anywhere;
}
.empty {
  padding: 14px 15px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px dashed #cbd7e4;
  color: #6d7889;
  font-size: 15px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.week-shell {
  border-radius: 18px;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid #d8e3ee;
  box-shadow:
    12px 16px 36px rgba(31, 41, 55, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.96);
}
.week-grid {
  display: grid;
  grid-template-columns: 72px repeat(7, 1fr);
  width: 100%;
}
.corner,
.day-head {
  height: 54px;
  padding: 10px 8px;
  background: #f7f9fc;
  border-bottom: 1px solid #d8e3ee;
}
.corner {
  border-right: 1px solid #d8e3ee;
}
.day-head {
  text-align: center;
  border-right: 1px solid #d8e3ee;
}
.day-head:last-child {
  border-right: 0;
}
.day-name {
  font-size: 16px;
  font-weight: 900;
  line-height: 1.15;
  color: #263247;
}
.day-date {
  margin-top: 4px;
  font-size: 12px;
  color: #7b8796;
}
.time-axis,
.day-column {
  position: relative;
  min-height: var(--grid-height);
}
.time-axis {
  background: #f8fafc;
  border-right: 1px solid #d8e3ee;
}
.day-column {
  background: #ffffff;
  border-right: 1px solid #e0e8f1;
}
.day-column:last-child {
  border-right: 0;
}
.grid-line {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: #eef3f8;
  pointer-events: none;
}
.grid-line.course-boundary {
  left: 10px;
  right: 10px;
  background: rgba(79, 131, 196, 0.16);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.78);
}
.time-axis .grid-line {
  background: #dfe7f0;
}
.time-label {
  position: absolute;
  left: 8px;
  right: 8px;
  transform: translateY(-50%);
  color: #718094;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  text-align: right;
  white-space: nowrap;
}
.week-course {
  position: absolute;
  left: 10px;
  right: 10px;
  min-height: 28px;
  padding: 8px 9px;
  border-radius: 13px;
  overflow: hidden;
  background: linear-gradient(145deg, #eaf3ff, #ffffff);
  border: 1px solid #cbdcf1;
  border-left: 5px solid #4f83c4;
  box-shadow: 0 8px 18px rgba(49, 93, 145, 0.12);
}
.week-course:nth-child(3n + 1) {
  background: linear-gradient(145deg, #ecf8f2, #ffffff);
  border-color: #c9e6d7;
  border-left-color: #39a071;
}
.week-course:nth-child(3n + 2) {
  background: linear-gradient(145deg, #fff5e8, #ffffff);
  border-color: #ead9bf;
  border-left-color: #d28b43;
}
.week-course-title {
  font-size: 13px;
  line-height: 1.25;
  font-weight: 900;
  color: #203049;
  overflow-wrap: anywhere;
}
.week-course-meta {
  margin-top: 4px;
  color: #5f6f82;
  font-size: 11px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.report-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(145deg, #ffffff, #f5f8fc);
  border: 1px solid #dce5ef;
  box-shadow: 0 10px 24px rgba(31, 41, 55, 0.07);
}
.row-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.rank {
  flex: 0 0 auto;
  min-width: 42px;
  padding: 7px 8px;
  border-radius: 999px;
  background: #edf4ff;
  border: 1px solid #cbdcf1;
  color: #315d91;
  font-size: 16px;
  font-weight: 900;
  text-align: center;
}
.member-name {
  font-size: 17px;
  line-height: 1.3;
  font-weight: 900;
  color: #263247;
  overflow-wrap: anywhere;
}
.hours {
  flex: 0 0 auto;
  font-size: 24px;
  font-weight: 900;
  color: #b24f42;
  white-space: nowrap;
}
</style>
"""


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _fmt_range(item: ClassOccurrence) -> str:
    return f"{_fmt_time(item.start)} - {_fmt_time(item.end)}"


def _html(value: object) -> str:
    return escape(str(value), quote=True)


def _remaining_text(now: datetime, end: datetime) -> str:
    minutes = max(0, int((end - now).total_seconds() // 60))
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"还剩 {hours} 小时 {mins} 分钟"
    return f"还剩 {mins} 分钟"


def _qq_avatar_url(user_id: str) -> str:
    return f"https://q1.qlogo.cn/g?b=qq&nk={_html(user_id)}&s=100"


def _avatar(member: ScheduleMember, avatar_url: str | None = None, small: bool = False) -> str:
    url = avatar_url or _qq_avatar_url(member.user_id)
    size_class = " small" if small else ""
    return (
        f'<img class="avatar{size_class}" src="{_html(url)}" '
        f'alt="{_html(member.display_name)} 的头像">'
    )


def _frame(width: int, height: int, body: str) -> str:
    return (
        f'{STYLE}<div class="render-frame" data-render-width="{width}" '
        f'data-render-height="{height}" style="width:{width}px;min-height:{height}px">'
        f'{body}</div>'
    )


def _header(
    title: str,
    subtitle: str,
    pill: str,
    member: ScheduleMember | None = None,
    avatar_url: str | None = None,
) -> str:
    avatar = _avatar(member, avatar_url) if member else ""
    return f"""
  <div class="header">
    <div class="identity">
      {avatar}
      <div class="title-wrap">
        <div class="title">{_html(title)}</div>
        <div class="subtitle">{_html(subtitle)}</div>
      </div>
    </div>
    <div class="pill">{_html(pill)}</div>
  </div>"""


def status_html(
    status: CurrentStatus,
    now: datetime,
    requester_allowed: bool = True,
    avatar_url: str | None = None,
) -> str:
    member = status.member
    if not requester_allowed:
        content = '<div class="status">这位同学设置了隐私课表</div><div class="empty">当前状态和课表都不可查询。</div>'
        block_count = 1
    elif status.active:
        courses = []
        for item in status.active:
            courses.append(
                f'<div class="course"><div class="course-name">{_html(item.title)}</div>'
                f'<div class="muted">{_fmt_range(item)} · {_remaining_text(now, item.end)}</div>'
                f'<div class="muted">{_html(item.location)}</div></div>'
            )
        content = '<div class="status">正在上课中</div>' + "".join(courses)
        block_count = len(status.active)
    elif status.next_class:
        item = status.next_class
        content = (
            '<div class="status">现在没有课</div>'
            f'<div class="course"><div class="course-name">下一节：{_html(item.title)}</div>'
            f'<div class="muted">{item.start.strftime("%m-%d")} {_fmt_range(item)}</div>'
            f'<div class="muted">{_html(item.location)}</div></div>'
        )
        block_count = 1
    else:
        content = '<div class="status">现在没有课</div><div class="empty">未来两周内没有找到课程。</div>'
        block_count = 1
    height = 230 + max(1, block_count) * 132
    body = f"""<div class="surface">
{_header(f"{member.display_name} 的上课状态", now.strftime("%Y-%m-%d %H:%M"), "实时状态", member, avatar_url)}
  <div class="hero">{content}</div>
</div>"""
    return _frame(STATUS_WIDTH, height, body)


def _minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _time_bounds(occurrences: list[ClassOccurrence]) -> tuple[int, int]:
    if not occurrences:
        return 8 * 60, 18 * 60
    starts = [_minute_of_day(item.start) for item in occurrences]
    ends = [_minute_of_day(item.end) for item in occurrences]
    start = max(0, floor((min(starts) - 20) / 30) * 30)
    end = min(24 * 60, ceil((max(ends) + 20) / 30) * 30)
    if end - start < MIN_GRID_MINUTES:
        extra = MIN_GRID_MINUTES - (end - start)
        start = max(0, start - extra // 2)
        end = min(24 * 60, start + MIN_GRID_MINUTES)
    return start, end


def _time_label(minute: int) -> str:
    hour, mins = divmod(minute, 60)
    return f"{hour:02d}:{mins:02d}"


def _grid_top(minute: int, start_minute: int, total_minutes: int, grid_height: int) -> float:
    return (minute - start_minute) / total_minutes * grid_height


def _grid_lines(
    minutes: list[int],
    boundary_minutes: set[int],
    start_minute: int,
    total_minutes: int,
    grid_height: int,
) -> str:
    lines = []
    for minute in minutes:
        line_class = "grid-line course-boundary" if minute in boundary_minutes else "grid-line"
        top = _grid_top(minute, start_minute, total_minutes, grid_height)
        lines.append(f'<div class="{line_class}" style="top:{top:.2f}px"></div>')
    return "".join(lines)


def week_html(
    member: ScheduleMember,
    week_start: datetime,
    occurrences: list[ClassOccurrence],
    avatar_url: str | None = None,
) -> str:
    start_minute, end_minute = _time_bounds(occurrences)
    total_minutes = max(MIN_GRID_MINUTES, end_minute - start_minute)
    grid_height = max(360, total_minutes)
    height = 190 + 54 + grid_height
    items_by_day: dict[int, list[ClassOccurrence]] = defaultdict(list)
    for item in sorted(occurrences, key=lambda occ: (occ.start, occ.end)):
        day_index = (item.start.date() - week_start.date()).days
        if 0 <= day_index <= 6:
            items_by_day[day_index].append(item)

    heads = ['<div class="corner"></div>']
    columns = [
        f'<div class="time-axis" style="--grid-height:{grid_height}px">'
    ]
    label_step = 60 if total_minutes <= 720 else 120
    first_label = ceil(start_minute / label_step) * label_step
    hour_label_minutes = list(range(first_label, end_minute + 1, label_step))
    base_line_minutes = sorted(set(hour_label_minutes) | {start_minute, end_minute})
    columns.append(_grid_lines(base_line_minutes, set(), start_minute, total_minutes, grid_height))
    for minute in hour_label_minutes:
        top = _grid_top(minute, start_minute, total_minutes, grid_height)
        columns.append(
            f'<div class="time-label" style="top:{top:.2f}px">{_time_label(minute)}</div>'
        )
    columns.append("</div>")

    for offset in range(7):
        day = week_start + timedelta(days=offset)
        heads.append(
            f'<div class="day-head"><div class="day-name">{DAYS[offset]}</div>'
            f'<div class="day-date">{day.strftime("%m-%d")}</div></div>'
        )
        courses = []
        boundary_minutes: set[int] = set()
        for item in items_by_day.get(offset, []):
            item_start = max(start_minute, _minute_of_day(item.start))
            item_end = min(end_minute, _minute_of_day(item.end))
            if start_minute <= item_start <= end_minute:
                boundary_minutes.add(item_start)
            if start_minute <= item_end <= end_minute:
                boundary_minutes.add(item_end)
            top = _grid_top(item_start, start_minute, total_minutes, grid_height)
            course_height = max(30, (item_end - item_start) / total_minutes * grid_height)
            location = f'<div class="week-course-meta">{_html(item.location)}</div>' if item.location else ""
            courses.append(
                f'<div class="week-course" style="top:{top:.2f}px;height:{course_height:.2f}px">'
                f'<div class="week-course-title">{_html(item.title)}</div>'
                f'<div class="week-course-meta">{_fmt_range(item)}</div>{location}</div>'
            )
        if not courses:
            courses.append('<div class="empty" style="margin:12px">没课</div>')
        line_minutes = sorted(set(base_line_minutes) | boundary_minutes)
        columns.append(
            f'<div class="day-column" style="--grid-height:{grid_height}px">'
            f'{_grid_lines(line_minutes, boundary_minutes, start_minute, total_minutes, grid_height)}'
            f'{"".join(courses)}</div>'
        )

    body = f"""<div class="surface">
{_header(f"{member.display_name} 的本周课表", f'{week_start.strftime("%Y-%m-%d")} 起 · {len(occurrences)} 节课', "周视图", member, avatar_url)}
  <div class="week-shell">
    <div class="week-grid">{"".join(heads)}{"".join(columns)}</div>
  </div>
</div>"""
    return _frame(WEEK_WIDTH, height, body)


def report_html(group_name: str, day: datetime, rows: list[DailyReportRow]) -> str:
    if rows:
        row_html = []
        for idx, row in enumerate(rows, 1):
            hours = row.minutes / 60
            row_html.append(
                f'<div class="row"><div class="row-left"><div class="rank">#{idx}</div>'
                f'{_avatar(row.member, small=True)}'
                f'<div><div class="member-name">{_html(row.member.display_name)}</div>'
                f'<div class="muted">{row.class_count} 节课 · {row.minutes} 分钟</div></div></div>'
                f'<div class="hours">{hours:.1f} h</div></div>'
            )
        content = f'<div class="report-list">{"".join(row_html)}</div>'
    else:
        content = '<div class="hero"><div class="status">今天大家都没有课</div><div class="empty">没有可展示的课时排行。</div></div>'
    height = 170 + max(1, len(rows)) * 78
    body = f"""<div class="surface">
{_header(f"{group_name or '群聊'} 今日课时小结", f'{day.strftime("%Y-%m-%d")} · 仅统计非私密且当天有课的成员', "日报")}
  {content}
</div>"""
    return _frame(REPORT_WIDTH, height, body)


def message_html(title: str, message: str) -> str:
    body = f"""<div class="surface">
{_header(title, "Schedule Tracker", "提示")}
  <div class="hero"><div class="status">{_html(message)}</div></div>
</div>"""
    return _frame(STATUS_WIDTH, 300, body)


def privacy_label(mode: PrivacyMode) -> str:
    if mode == PrivacyMode.PUBLIC:
        return "公开"
    if mode == PrivacyMode.STATUS_ONLY:
        return "状态可查"
    return "私密"
