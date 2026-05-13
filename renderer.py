from __future__ import annotations

from datetime import datetime, timedelta

from .models import ClassOccurrence, CurrentStatus, DailyReportRow, PrivacyMode, ScheduleMember


STYLE = """
<style>
body {
  margin: 0;
  width: 880px;
  height: auto;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  color: #42372f;
  background: #fff7ed;
}
.card {
  box-sizing: border-box;
  width: 880px;
  min-height: 320px;
  padding: 34px;
  background:
    radial-gradient(circle at 82px 74px, #ffd6e7 0 34px, transparent 35px),
    radial-gradient(circle at 780px 88px, #c6f6d5 0 46px, transparent 47px),
    linear-gradient(135deg, #fff8e8 0%, #eef8ff 100%);
  border: 10px solid #ffe0ad;
}
.title { font-size: 34px; font-weight: 800; margin-bottom: 8px; }
.subtitle { font-size: 18px; color: #7a6a5d; margin-bottom: 24px; }
.pill {
  display: inline-block;
  padding: 8px 14px;
  border-radius: 999px;
  background: #ffffffcc;
  border: 2px solid #ffd39a;
  font-size: 18px;
  margin-right: 8px;
}
.hero {
  padding: 24px;
  border-radius: 26px;
  background: #ffffffd9;
  border: 3px dashed #ffb6c8;
}
.status { font-size: 30px; font-weight: 800; margin-bottom: 14px; }
.course {
  margin-top: 12px;
  padding: 16px;
  border-radius: 18px;
  background: #f7fbff;
  border-left: 10px solid #84c5ff;
}
.course-name { font-size: 24px; font-weight: 700; }
.muted { color: #756b61; font-size: 17px; margin-top: 6px; }
.grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px; }
.day {
  min-height: 260px;
  padding: 12px;
  border-radius: 18px;
  background: #ffffffbf;
  border: 2px solid #ffe0ad;
}
.day-title { font-size: 18px; font-weight: 800; margin-bottom: 10px; }
.mini {
  margin: 8px 0;
  padding: 8px;
  border-radius: 12px;
  background: #eef8ff;
  font-size: 14px;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 10px 0;
  padding: 14px 18px;
  border-radius: 16px;
  background: #ffffffc9;
  border: 2px solid #f7d9b6;
}
.rank { font-size: 22px; font-weight: 800; }
.hours { font-size: 24px; font-weight: 800; color: #e66a5f; }
</style>
"""


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _fmt_range(item: ClassOccurrence) -> str:
    return f"{_fmt_time(item.start)} - {_fmt_time(item.end)}"


def _remaining_text(now: datetime, end: datetime) -> str:
    minutes = max(0, int((end - now).total_seconds() // 60))
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"还剩 {hours} 小时 {mins} 分钟"
    return f"还剩 {mins} 分钟"


def status_html(status: CurrentStatus, now: datetime, requester_allowed: bool = True) -> str:
    member = status.member
    if not requester_allowed:
        content = '<div class="status">这位同学设置了私密课表</div><div class="muted">现在状态和课表都不可查询。</div>'
    elif status.active:
        courses = []
        for item in status.active:
            courses.append(
                f'<div class="course"><div class="course-name">{item.title}</div>'
                f'<div class="muted">{_fmt_range(item)} · {_remaining_text(now, item.end)}</div>'
                f'<div class="muted">{item.location}</div></div>'
            )
        content = '<div class="status">正在上课中</div>' + "".join(courses)
    elif status.next_class:
        item = status.next_class
        content = (
            '<div class="status">现在没有课</div>'
            f'<div class="course"><div class="course-name">下一节：{item.title}</div>'
            f'<div class="muted">{item.start.strftime("%m-%d")} {_fmt_range(item)}</div>'
            f'<div class="muted">{item.location}</div></div>'
        )
    else:
        content = '<div class="status">现在没有课</div><div class="muted">未来两周内没有找到课程。</div>'
    return f"""{STYLE}<div class="card">
  <div class="title">{member.display_name} 的上课状态</div>
  <div class="subtitle">{now.strftime("%Y-%m-%d %H:%M")}</div>
  <div class="hero">{content}</div>
</div>"""


def week_html(member: ScheduleMember, week_start: datetime, occurrences: list[ClassOccurrence]) -> str:
    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_items = [item for item in occurrences if item.start.date() == day.date()]
        parts = [
            f'<div class="day-title">{day.strftime("%a")}<br>{day.strftime("%m-%d")}</div>'
        ]
        if not day_items:
            parts.append('<div class="muted">没课</div>')
        for item in day_items:
            parts.append(
                f'<div class="mini"><b>{item.title}</b><br>{_fmt_range(item)}'
                f'<br>{item.location}</div>'
            )
        days.append(f'<div class="day">{"".join(parts)}</div>')
    return f"""{STYLE}<div class="card">
  <div class="title">{member.display_name} 的本周课表</div>
  <div class="subtitle">{week_start.strftime("%Y-%m-%d")} 起</div>
  <div class="grid">{"".join(days)}</div>
</div>"""


def report_html(group_name: str, day: datetime, rows: list[DailyReportRow]) -> str:
    if rows:
        body = []
        for idx, row in enumerate(rows, 1):
            hours = row.minutes / 60
            body.append(
                f'<div class="row"><div><span class="rank">#{idx}</span> '
                f'{row.member.display_name}<div class="muted">{row.class_count} 节课</div></div>'
                f'<div class="hours">{hours:.1f} h</div></div>'
            )
        content = "".join(body)
    else:
        content = '<div class="hero"><div class="status">今天大家都没有课</div></div>'
    return f"""{STYLE}<div class="card">
  <div class="title">{group_name or "群聊"} 今日课时小结</div>
  <div class="subtitle">{day.strftime("%Y-%m-%d")} · 仅统计非私密且当天有课的成员</div>
  {content}
</div>"""


def message_html(title: str, message: str) -> str:
    return f"""{STYLE}<div class="card">
  <div class="title">{title}</div>
  <div class="hero"><div class="status">{message}</div></div>
</div>"""


def privacy_label(mode: PrivacyMode) -> str:
    if mode == PrivacyMode.PUBLIC:
        return "公开"
    if mode == PrivacyMode.STATUS_ONLY:
        return "状态可查"
    return "私密"
