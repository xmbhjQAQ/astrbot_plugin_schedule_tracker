from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    AsyncIOScheduler = None
    CronTrigger = None

from astrbot.api import AstrBotConfig, logger, star
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
from astrbot.api.message_components import At, File
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .ics_parser import CalendarDependencyError, CalendarParseError, IcsScheduleParser
from .models import FileCandidate, PrivacyMode
from .renderer import privacy_label, report_html, status_html, week_html
from .service import ScheduleService
from .storage import ScheduleStorage


PLUGIN_NAME = "astrbot_plugin_schedule_tracker"
RECENT_FILE_WINDOW = timedelta(minutes=10)


@star.register(PLUGIN_NAME, "xmbhjQAQ", "QQ群 ICS 课表追踪插件", "0.1.0")
class ScheduleTrackerPlugin(star.Star):
    def __init__(self, context: star.Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        timezone_name = str(self.config.get("timezone", "Asia/Shanghai"))
        try:
            self.timezone = ZoneInfo(timezone_name)
        except Exception:
            logger.warning("课表插件时区配置无效，回退到 Asia/Shanghai: %s", timezone_name)
            self.timezone = ZoneInfo("Asia/Shanghai")
        data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.storage = ScheduleStorage(data_dir)
        self.groups = self.storage.load_groups()
        self.parser = IcsScheduleParser(self.timezone)
        self.service = ScheduleService(self.parser, self.timezone)
        self.recent_files: dict[tuple[str, str], FileCandidate] = {}
        self.pending_binds: dict[tuple[str, str], datetime] = {}
        self.scheduler: Any = None
        self._configure_report_job()

    def _configure_report_job(self) -> None:
        if AsyncIOScheduler is None or CronTrigger is None:
            logger.warning("缺少 apscheduler，课表自动日报已禁用。")
            return
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        report_time = str(self.config.get("daily_report_time", "22:30"))
        try:
            hour_text, minute_text = report_time.split(":", 1)
            trigger = CronTrigger(
                hour=int(hour_text),
                minute=int(minute_text),
                timezone=self.timezone,
            )
        except Exception:
            logger.warning("课表日报时间配置无效，回退到 22:30: %s", report_time)
            trigger = CronTrigger(hour=22, minute=30, timezone=self.timezone)
        self.scheduler.add_job(
            self._send_daily_reports,
            trigger,
            id="schedule_tracker_daily_report",
            replace_existing=True,
        )
        try:
            self.scheduler.start()
        except RuntimeError:
            logger.warning("课表插件定时器启动失败，将跳过自动日报。")

    async def terminate(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent) -> None:
        if await self._remember_ics_files(event):
            return
        text = event.message_str.strip()
        if text == "绑定课表":
            await self._handle_bind(event)
        elif text.startswith("在上课吗"):
            await self._handle_status(event)
        elif text.startswith("看看课表"):
            await self._handle_week(event)
        elif text.startswith("课表隐私"):
            await self._handle_privacy(event, text)
        elif text == "删除课表":
            await self._handle_delete(event)

    async def _remember_ics_files(self, event: AstrMessageEvent) -> bool:
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not group_id or not user_id:
            return False
        for component in event.get_messages():
            if not isinstance(component, File):
                continue
            name = component.name or ""
            if not name.lower().endswith(".ics"):
                continue
            file_ref = component.url or getattr(component, "file_", "")
            if not file_ref:
                continue
            candidate = FileCandidate(
                group_id=group_id,
                user_id=user_id,
                display_name=event.get_sender_name() or user_id,
                file_name=name,
                file_url=file_ref,
                created_at=datetime.now(self.timezone),
            )
            self.recent_files[(group_id, user_id)] = candidate
            pending_at = self.pending_binds.get((group_id, user_id))
            if pending_at and candidate.created_at - pending_at <= RECENT_FILE_WINDOW:
                self.pending_binds.pop((group_id, user_id), None)
                await self._bind_candidate(event, candidate, component)
                return True
        return False

    def _target_from_at(self, event: AstrMessageEvent) -> tuple[str, str] | None:
        bot_id = event.get_self_id()
        for component in event.get_messages():
            if isinstance(component, At) and str(component.qq) not in {"all", bot_id}:
                return str(component.qq), component.name or str(component.qq)
        return None

    async def _render_image(self, html: str) -> str:
        return await self.html_render(
            html,
            {},
            options={
                "type": "png",
                "full_page": True,
            },
        )

    async def _reply_html(
        self,
        event: AstrMessageEvent,
        html: str,
    ) -> None:
        try:
            url = await self._render_image(html)
            event.set_result(MessageEventResult().url_image(url).stop_event())
        except Exception as exc:
            logger.exception("课表图片渲染失败: %s", exc)
            self._reply_text(event, "课表图片渲染失败，请稍后再试。")

    def _reply_text(self, event: AstrMessageEvent, text: str) -> None:
        event.set_result(
            MessageEventResult().message(text).use_t2i(False).stop_event()
        )

    async def _handle_bind(self, event: AstrMessageEvent) -> None:
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        candidate = self.recent_files.get((group_id, user_id))
        now = datetime.now(self.timezone)
        if not candidate or now - candidate.created_at > RECENT_FILE_WINDOW:
            self.pending_binds[(group_id, user_id)] = now
            self._reply_text(event, "请在 10 分钟内上传或转发自己的 .ics 文件。")
            return

        await self._bind_candidate(event, candidate, None)

    async def _bind_candidate(
        self,
        event: AstrMessageEvent,
        candidate: FileCandidate,
        component: File | None,
    ) -> None:
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        now = datetime.now(self.timezone)
        file_path = ""
        if component is not None:
            file_path = await component.get_file()
        if not file_path:
            if candidate.file_url.startswith(("http://", "https://")):
                temp_file = File(name=candidate.file_name, url=candidate.file_url)
            else:
                temp_file = File(name=candidate.file_name, file=candidate.file_url)
            file_path = await temp_file.get_file()
        if not file_path:
            self._reply_text(event, "没有拿到可下载的 ICS 文件。")
            return

        try:
            self.parser.occurrences_between(file_path, now, now + timedelta(days=7))
        except CalendarDependencyError as exc:
            self._reply_text(event, str(exc))
            return
        except CalendarParseError:
            self._reply_text(event, "这个 ICS 文件解析失败，请检查文件格式。")
            return

        member = self.storage.bind_schedule(
            self.groups,
            group_id=group_id,
            unified_msg_origin=event.unified_msg_origin,
            user_id=user_id,
            display_name=event.get_sender_name() or user_id,
            source_path=file_path,
            timezone=self.timezone,
        )
        self._reply_text(event, f"{member.display_name} 的课表已绑定，默认公开。")

    async def _handle_status(self, event: AstrMessageEvent) -> None:
        target = self._target_from_at(event)
        if not target:
            self._reply_text(event, "请 @ 一位要查询的群友。")
            return
        target_id, _ = target
        member = self.groups.get(event.get_group_id(), None)
        schedule = member.members.get(target_id) if member else None
        if not schedule:
            self._reply_text(event, "这位群友还没有绑定课表。")
            return
        if schedule.privacy == PrivacyMode.PRIVATE and target_id != event.get_sender_id():
            self._reply_text(event, "这位同学设置了私密，不能查询当前状态。")
            return
        now = datetime.now(self.timezone)
        try:
            status = self.service.current_status(schedule, now)
            await self._reply_html(event, status_html(status, now))
        except (CalendarDependencyError, CalendarParseError) as exc:
            self._reply_text(event, str(exc))

    async def _handle_week(self, event: AstrMessageEvent) -> None:
        target = self._target_from_at(event)
        if not target:
            self._reply_text(event, "请 @ 一位要查询的群友。")
            return
        target_id, _ = target
        group = self.groups.get(event.get_group_id())
        member = group.members.get(target_id) if group else None
        if not member:
            self._reply_text(event, "这位群友还没有绑定课表。")
            return
        if member.privacy != PrivacyMode.PUBLIC and target_id != event.get_sender_id():
            self._reply_text(event, "这位同学没有公开完整课表。")
            return
        try:
            week_start, occurrences = self.service.week_schedule(member, datetime.now(self.timezone))
            await self._reply_html(event, week_html(member, week_start, occurrences))
        except (CalendarDependencyError, CalendarParseError) as exc:
            self._reply_text(event, str(exc))

    async def _handle_privacy(self, event: AstrMessageEvent, text: str) -> None:
        mapping = {
            "公开": PrivacyMode.PUBLIC,
            "状态可查": PrivacyMode.STATUS_ONLY,
            "私密": PrivacyMode.PRIVATE,
        }
        mode = next((value for key, value in mapping.items() if text.endswith(key)), None)
        if mode is None:
            self._reply_text(event, "可选：课表隐私 公开 / 状态可查 / 私密")
            return
        member = self.storage.set_privacy(
            self.groups,
            group_id=event.get_group_id(),
            user_id=event.get_sender_id(),
            privacy=mode,
        )
        if not member:
            self._reply_text(event, "请先绑定课表。")
            return
        self._reply_text(event, f"已切换为：{privacy_label(mode)}")

    async def _handle_delete(self, event: AstrMessageEvent) -> None:
        member = self.storage.delete_schedule(
            self.groups,
            group_id=event.get_group_id(),
            user_id=event.get_sender_id(),
        )
        self.recent_files.pop((event.get_group_id(), event.get_sender_id()), None)
        self.pending_binds.pop((event.get_group_id(), event.get_sender_id()), None)
        if not member:
            self._reply_text(event, "你还没有绑定课表。")
            return
        self._reply_text(event, "已删除你的课表绑定。")

    async def _send_daily_reports(self) -> None:
        today = datetime.now(self.timezone).date()
        for group in self.groups.values():
            public_group = type(group)(
                group_id=group.group_id,
                unified_msg_origin=group.unified_msg_origin,
                members={
                    user_id: member
                    for user_id, member in group.members.items()
                    if member.privacy != PrivacyMode.PRIVATE
                },
            )
            if not public_group.unified_msg_origin:
                continue
            try:
                rows = self.service.daily_report(public_group, today)
                if not rows:
                    continue
                html = report_html(public_group.group_id, datetime.now(self.timezone), rows)
                url = await self._render_image(html)
                await self.context.send_message(public_group.unified_msg_origin, MessageChain().url_image(url))
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.exception("发送课表日报失败 group=%s: %s", group.group_id, exc)
