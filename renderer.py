from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from .models import ClassOccurrence, CurrentStatus, DailyReportRow, PrivacyMode, ScheduleMember


STYLE = """
<style>
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  width: 760px;
  height: auto;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  color: #252a31;
  background: #f4f7fb;
}
.card {
  width: 760px;
  padding: 26px;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.78)),
    linear-gradient(135deg, #e8f1ff 0%, #f9f3e8 48%, #eef8f2 100%);
  border: 1px solid #dbe4ef;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid #d8e2ee;
  margin-bottom: 18px;
}
.header > div:first-child {
  min-width: 0;
}
.title {
  min-width: 0;
  font-size: 28px;
  line-height: 1.22;
  font-weight: 800;
  color: #1c2430;
  overflow-wrap: anywhere;
}
.subtitle {
  margin-top: 7px;
  font-size: 15px;
  line-height: 1.45;
  color: #637083;
  overflow-wrap: anywhere;
}
.pill {
  flex: 0 0 auto;
  display: inline-block;
  padding: 7px 12px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid #cfd9e6;
  color: #4d5a6b;
  font-size: 14px;
  font-weight: 700;
}
.hero {
  padding: 18px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #d9e3ef;
  box-shadow: 0 10px 24px rgba(40, 54, 75, 0.08);
}
.status {
  font-size: 23px;
  line-height: 1.32;
  font-weight: 800;
  color: #172033;
  overflow-wrap: anywhere;
}
.status + .muted,
.status + .empty,
.status + .course {
  margin-top: 12px;
}
.course {
  margin-top: 12px;
  padding: 14px 16px;
  border-radius: 8px;
  background: #f7fbff;
  border: 1px solid #cfe0f2;
  border-left: 5px solid #4f83c4;
}
.course-name {
  font-size: 20px;
  line-height: 1.36;
  font-weight: 800;
  color: #203049;
  overflow-wrap: anywhere;
}
.muted {
  color: #647184;
  font-size: 15px;
  line-height: 1.48;
  margin-top: 5px;
  overflow-wrap: anywhere;
}
.week-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}
.day {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 14px;
  padding: 14px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #dce5ef;
}
.day-title {
  font-size: 18px;
  line-height: 1.35;
  font-weight: 800;
  color: #233047;
}
.day-date {
  margin-top: 4px;
  font-size: 13px;
  color: #7a8798;
}
.day-courses {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  min-width: 0;
}
.mini {
  padding: 11px 12px;
  border-radius: 8px;
  background: #f5f8fc;
  border: 1px solid #e0e8f1;
  font-size: 14px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.mini-title {
  font-size: 16px;
  font-weight: 800;
  color: #233047;
  margin-bottom: 4px;
}
.empty {
  padding: 13px 14px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px dashed #cbd7e4;
  color: #6d7889;
  font-size: 15px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  margin: 10px 0;
  padding: 15px 17px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #dce5ef;
}
.row-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.row-left > div:last-child {
  min-width: 0;
}
.member-name {
  font-size: 18px;
  line-height: 1.35;
  font-weight: 800;
  color: #263247;
  overflow-wrap: anywhere;
}
.rank {
  flex: 0 0 auto;
  min-width: 44px;
  padding: 7px 9px;
  border-radius: 999px;
  background: #edf4ff;
  border: 1px solid #cbdcf1;
  color: #315d91;
  font-size: 17px;
  font-weight: 800;
  text-align: center;
}
.hours {
  flex: 0 0 auto;
  font-size: 24px;
  font-weight: 800;
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


def status_html(status: CurrentStatus, now: datetime, requester_allowed: bool = True) -> str:
    member = status.member
    if not requester_allowed:
        content = '<div class="status">这位同学设置了私密课表</div><div class="empty">现在状态和课表都不可查询。</div>'
    elif status.active:
        courses = []
        for item in status.active:
            courses.append(
                f'<div class="course"><div class="course-name">{_html(item.title)}</div>'
                f'<div class="muted">{_fmt_range(item)} · {_remaining_text(now, item.end)}</div>'
                f'<div class="muted">{_html(item.location)}</div></div>'
            )
        content = '<div class="status">正在上课中</div>' + "".join(courses)
    elif status.next_class:
        item = status.next_class
        content = (
            '<div class="status">现在没有课</div>'
            f'<div class="course"><div class="course-name">下一节：{_html(item.title)}</div>'
            f'<div class="muted">{item.start.strftime("%m-%d")} {_fmt_range(item)}</div>'
            f'<div class="muted">{_html(item.location)}</div></div>'
        )
    else:
        content = '<div class="status">现在没有课</div><div class="empty">未来两周内没有找到课程。</div>'
    return f"""{STYLE}<div class="card">
  <div class="header">
    <div>
      <div class="title">{_html(member.display_name)} 的上课状态</div>
      <div class="subtitle">{now.strftime("%Y-%m-%d %H:%M")}</div>
    </div>
    <div class="pill">实时状态</div>
  </div>
  <div class="hero">{content}</div>
</div>"""


def week_html(member: ScheduleMember, week_start: datetime, occurrences: list[ClassOccurrence]) -> str:
    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_items = [item for item in occurrences if item.start.date() == day.date()]
        parts = [
            f'<div><div class="day-title">{day.strftime("%a")}</div>'
            f'<div class="day-date">{day.strftime("%m-%d")}</div></div>'
        ]
        if not day_items:
            parts.append('<div class="empty">没课</div>')
        else:
            courses = []
            for item in day_items:
                courses.append(
                    f'<div class="mini"><div class="mini-title">{_html(item.title)}</div>'
                    f'<div>{_fmt_range(item)}</div><div class="muted">{_html(item.location)}</div></div>'
                )
            parts.append(f'<div class="day-courses">{"".join(courses)}</div>')
        days.append(f'<div class="day">{"".join(parts)}</div>')
    return f"""{STYLE}<div class="card">
  <div class="header">
    <div>
      <div class="title">{_html(member.display_name)} 的本周课表</div>
      <div class="subtitle">{week_start.strftime("%Y-%m-%d")} 起</div>
    </div>
    <div class="pill">7 天</div>
  </div>
  <div class="week-list">{"".join(days)}</div>
</div>"""


def report_html(group_name: str, day: datetime, rows: list[DailyReportRow]) -> str:
    if rows:
        body = []
        for idx, row in enumerate(rows, 1):
            hours = row.minutes / 60
            body.append(
                f'<div class="row"><div class="row-left"><div class="rank">#{idx}</div>'
                f'<div><div class="member-name">{_html(row.member.display_name)}</div>'
                f'<div class="muted">{row.class_count} 节课</div></div></div>'
                f'<div class="hours">{hours:.1f} h</div></div>'
            )
        content = "".join(body)
    else:
        content = '<div class="hero"><div class="status">今天大家都没有课</div><div class="empty">没有可展示的课时排行。</div></div>'
    return f"""{STYLE}<div class="card">
  <div class="header">
    <div>
      <div class="title">{_html(group_name or "群聊")} 今日课时小结</div>
      <div class="subtitle">{day.strftime("%Y-%m-%d")} · 仅统计非私密且当天有课的成员</div>
    </div>
    <div class="pill">排行</div>
  </div>
  {content}
</div>"""


def message_html(title: str, message: str) -> str:
    return f"""{STYLE}<div class="card">
  <div class="header">
    <div>
      <div class="title">{_html(title)}</div>
    </div>
    <div class="pill">提示</div>
  </div>
  <div class="hero"><div class="status">{_html(message)}</div></div>
</div>"""


def privacy_label(mode: PrivacyMode) -> str:
    if mode == PrivacyMode.PUBLIC:
        return "公开"
    if mode == PrivacyMode.STATUS_ONLY:
        return "状态可查"
    return "私密"
