"""AstrBot entrypoint for the schedule tracker plugin.

This module keeps framework-specific concerns in one place: message routing,
reply rendering, permission checks, and scheduler lifecycle. File binding,
storage, parsing, and schedule calculations live in smaller helper modules.
"""

from __future__ import annotations

import asyncio
import json
import re
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

from .binding import ScheduleBinder
from .ics_parser import CalendarDependencyError, CalendarParseError, IcsScheduleParser
from .models import FileCandidate, PrivacyMode
from .recall import delayed_recall, send_group_image
from .renderer import privacy_label, report_html, status_html, week_html
from .service import ScheduleService
from .storage import ScheduleStorage


PLUGIN_NAME = "astrbot_plugin_schedule_tracker"
RECENT_FILE_WINDOW = timedelta(minutes=10)
DEFAULT_IMAGE_RECALL_SECONDS = 90
RENDER_SIZE_RE = re.compile(
    r'data-render-width="(\d+)".*?data-render-height="(\d+)"', re.S
)


@star.register(PLUGIN_NAME, "xmbhjQAQ", "QQ群 ICS 课表追踪插件", "0.1.0")
class ScheduleTrackerPlugin(star.Star):
    """Group-message command surface for querying and maintaining schedules."""

    def __init__(
        self, context: star.Context, config: AstrBotConfig | None = None
    ) -> None:
        super().__init__(context)
        self.config = config or {}
        timezone_name = str(self.config.get("timezone", "Asia/Shanghai"))
        try:
            self.timezone = ZoneInfo(timezone_name)
        except Exception:
            logger.warning(
                "课表插件时区配置无效，回退到 Asia/Shanghai: %s", timezone_name
            )
            self.timezone = ZoneInfo("Asia/Shanghai")
        data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.storage = ScheduleStorage(data_dir)
        self.groups = self.storage.load_groups()
        self.parser = IcsScheduleParser(self.timezone)
        self.service = ScheduleService(self.parser, self.timezone)
        self.binder = ScheduleBinder(
            parser=self.parser,
            storage=self.storage,
            groups=self.groups,
            timezone=self.timezone,
        )
        self.recent_files: dict[tuple[str, str], FileCandidate] = {}
        self.pending_binds: dict[tuple[str, str], datetime] = {}
        self.recall_tasks: set[asyncio.Task] = set()
        self.scheduler: Any = None
        self._configure_report_job()

    def _configure_report_job(self) -> None:
        """Start the optional APScheduler daily report job."""

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
        for task in self.recall_tasks:
            task.cancel()
        self.recall_tasks.clear()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent) -> None:
        if await self._remember_ics_files(event):
            return
        text = event.message_str.strip()
        if text == "绑定课表":
            await self._handle_bind(event)
        elif text == "如何添加课表":
            self._handle_how_to_add_schedule(event)
        elif text.startswith("在上课吗"):
            await self._handle_status(event)
        elif text.startswith("看看课表"):
            await self._handle_week(event)
        elif text.startswith("课表隐私"):
            await self._handle_privacy(event, text)
        elif text.startswith("课表日报"):
            await self._handle_daily_report_setting(event, text)
        elif text.startswith("课表撤回"):
            await self._handle_recall_setting(event, text)
        elif text == "删除课表":
            await self._handle_delete(event)

    async def _remember_ics_files(self, event: AstrMessageEvent) -> bool:
        """Remember recent ICS uploads so the next bind command can consume them."""

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

            # QQ forwarded files can arrive before the user sends "绑定课表".
            # Keep a short-lived candidate keyed by group and sender to avoid
            # binding someone else's file by accident.
            candidate = FileCandidate(
                group_id=group_id,
                user_id=user_id,
                display_name=event.get_sender_name() or user_id,
                file_name=name,
                file_url=file_ref,
                created_at=datetime.now(self.timezone),
                upload_message_id=str(getattr(event.message_obj, "message_id", "")),
            )
            self.recent_files[(group_id, user_id)] = candidate
            if self._auto_recall_ics_uploads_enabled(group_id):
                self._schedule_message_recall(
                    event,
                    candidate.upload_message_id,
                    int(RECENT_FILE_WINDOW.total_seconds()),
                )
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

    def _is_group_admin(self, group_id: str | None, user_id: str | None) -> bool:
        """Check the plugin-managed admin allowlist for a group."""

        if not group_id or not user_id:
            return False
        return user_id in self._group_admin_ids(group_id)

    def _has_group_admins(self, group_id: str | None) -> bool:
        return bool(group_id and self._configured_group_admins(group_id))

    def _configured_daily_report_groups(self) -> set[str]:
        raw = self.config.get("daily_report_enabled_groups", [])
        if not isinstance(raw, list):
            return set()
        return {str(group_id).strip() for group_id in raw if str(group_id).strip()}

    def _configured_group_admins(self, group_id: str) -> set[str]:
        """Read admin IDs from config, accepting JSON text or structured values."""

        raw = self.config.get("group_admins", {})
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "{}")
            except json.JSONDecodeError:
                logger.warning("课表插件 group_admins 配置不是有效 JSON。")
                return set()
        if not isinstance(raw, dict):
            return set()
        value = raw.get(group_id) or raw.get(str(group_id))
        if isinstance(value, list):
            return {str(user_id).strip() for user_id in value if str(user_id).strip()}
        if isinstance(value, str):
            return {user_id for user_id in re.split(r"[\s,，]+", value) if user_id}
        return set()

    def _group_admin_ids(self, group_id: str) -> set[str]:
        return self._configured_group_admins(group_id)

    def _daily_report_enabled(self, group: Any) -> bool:
        """Merge persisted group state with WebUI-configured defaults."""

        return bool(
            group.daily_report_enabled
            or group.group_id in self._configured_daily_report_groups()
        )

    def _config_bool(self, key: str, default: bool = False) -> bool:
        raw = self.config.get(key, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on", "开启"}
        return bool(raw)

    def _image_recall_seconds(self) -> int:
        try:
            seconds = int(
                self.config.get(
                    "schedule_image_recall_seconds", DEFAULT_IMAGE_RECALL_SECONDS
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_IMAGE_RECALL_SECONDS
        return max(1, seconds)

    def _auto_recall_ics_uploads_enabled(self, group_id: str | None) -> bool:
        group = self.groups.get(group_id or "")
        if group and group.auto_recall_ics_uploads is not None:
            return group.auto_recall_ics_uploads
        return self._config_bool("auto_recall_ics_uploads", False)

    def _auto_recall_schedule_images_enabled(self, group_id: str | None) -> bool:
        group = self.groups.get(group_id or "")
        if group and group.auto_recall_schedule_images is not None:
            return group.auto_recall_schedule_images
        return self._config_bool("auto_recall_schedule_images", False)

    def _save_plugin_config(self) -> None:
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            save_config()

    def _sync_daily_report_group_config(self, group_id: str, enabled: bool) -> None:
        groups = self.config.get("daily_report_enabled_groups", [])
        if not isinstance(groups, list):
            groups = []
        group_ids = {str(item).strip() for item in groups if str(item).strip()}
        if enabled:
            group_ids.add(group_id)
        else:
            group_ids.discard(group_id)
        self.config["daily_report_enabled_groups"] = sorted(group_ids)
        self._save_plugin_config()

    def _render_options(self, html: str) -> dict[str, Any]:
        """Build html_render screenshot options from renderer frame metadata."""

        options: dict[str, Any] = {
            "type": "png",
            "animations": "disabled",
            "caret": "hide",
        }
        match = RENDER_SIZE_RE.search(html)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            options["clip"] = {
                "x": 0,
                "y": 0,
                "width": width,
                "height": height,
            }
            return options
        options["full_page"] = True
        return options

    def _avatar_url(self, user_id: str) -> str:
        return f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100"

    async def _render_image(self, html: str) -> str:
        return await self.html_render(
            html,
            {},
            options=self._render_options(html),
        )

    async def _reply_html(
        self,
        event: AstrMessageEvent,
        html: str,
    ) -> None:
        """Render an HTML view and fall back to plain text on renderer failures."""

        try:
            url = await self._render_image(html)
            event.set_result(MessageEventResult().url_image(url).stop_event())
        except Exception as exc:
            logger.exception("课表图片渲染失败: %s", exc)
            self._reply_text(event, "课表图片渲染失败，请稍后再试。")

    async def _reply_query_html(
        self,
        event: AstrMessageEvent,
        html: str,
    ) -> None:
        """Reply with status/week images, optionally sending via OneBot for recall."""

        if not self._auto_recall_schedule_images_enabled(event.get_group_id()):
            await self._reply_html(event, html)
            return
        if event.get_platform_name() != "aiocqhttp" or not event.get_group_id():
            logger.warning("当前平台不支持课表图片自动撤回，已使用普通图片回复。")
            await self._reply_html(event, html)
            return
        try:
            url = await self._render_image(html)
            message_id = await send_group_image(event.bot, event.get_group_id(), url)
            self._schedule_onebot_recall(
                event.bot,
                message_id,
                self._image_recall_seconds(),
            )
            event.stop_event()
        except Exception as exc:
            logger.exception("课表图片发送或自动撤回调度失败: %s", exc)
            self._reply_text(event, "课表图片发送失败，请稍后再试。")

    def _reply_text(self, event: AstrMessageEvent, text: str) -> None:
        event.set_result(MessageEventResult().message(text).use_t2i(False).stop_event())

    def _handle_how_to_add_schedule(self, event: AstrMessageEvent) -> None:
        reply = str(
            self.config.get(
                "how_to_add_schedule_reply",
                "请发送“绑定课表”，然后在 10 分钟内上传或转发自己的 .ics 日历文件。",
            )
        ).strip()
        self._reply_text(
            event, reply or "请发送“绑定课表”，然后上传或转发自己的 .ics 日历文件。"
        )

    async def _handle_bind(self, event: AstrMessageEvent) -> None:
        """Bind the sender's most recent ICS upload, or ask them to upload one."""

        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        candidate = self.recent_files.get((group_id, user_id))
        now = datetime.now(self.timezone)
        if not candidate or now - candidate.created_at > RECENT_FILE_WINDOW:
            if not group_id or not user_id:
                self._reply_text(event, "只能在群聊中绑定自己的课表。")
                return
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
        """Delegate candidate binding and translate the result into a reply."""

        result = await self.binder.bind_candidate(event, candidate, component)
        if result.member and self._auto_recall_ics_uploads_enabled(
            event.get_group_id()
        ):
            self._schedule_message_recall(event, candidate.upload_message_id, 1)
        self._reply_text(event, result.message)

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
        if (
            schedule.privacy == PrivacyMode.PRIVATE
            and target_id != event.get_sender_id()
        ):
            self._reply_text(event, "这位同学设置了私密，不能查询当前状态。")
            return
        now = datetime.now(self.timezone)
        try:
            status = self.service.current_status(schedule, now)
            await self._reply_query_html(
                event, status_html(status, now, avatar_url=self._avatar_url(target_id))
            )
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
            week_start, occurrences = self.service.week_schedule(
                member, datetime.now(self.timezone)
            )
            await self._reply_query_html(
                event,
                week_html(
                    member,
                    week_start,
                    occurrences,
                    avatar_url=self._avatar_url(target_id),
                ),
            )
        except (CalendarDependencyError, CalendarParseError) as exc:
            self._reply_text(event, str(exc))

    async def _handle_privacy(self, event: AstrMessageEvent, text: str) -> None:
        mapping = {
            "公开": PrivacyMode.PUBLIC,
            "状态可查": PrivacyMode.STATUS_ONLY,
            "私密": PrivacyMode.PRIVATE,
        }
        mode = next(
            (value for key, value in mapping.items() if text.endswith(key)), None
        )
        if mode is None:
            self._reply_text(event, "可选：课表隐私 公开 / 状态可查 / 私密")
            return
        try:
            member = self.storage.set_privacy(
                self.groups,
                group_id=event.get_group_id(),
                user_id=event.get_sender_id(),
                privacy=mode,
            )
        except OSError as exc:
            logger.exception("保存课表隐私设置失败: %s", exc)
            self._reply_text(event, "隐私设置保存失败，请稍后再试。")
            return
        if not member:
            self._reply_text(event, "请先绑定课表。")
            return
        self._reply_text(event, f"已切换为：{privacy_label(mode)}")

    async def _handle_daily_report_setting(
        self, event: AstrMessageEvent, text: str
    ) -> None:
        group_id = event.get_group_id()
        if not group_id:
            self._reply_text(event, "课表日报只能在群聊中设置。")
            return
        action = text.removeprefix("课表日报").strip()
        group = self.groups.get(group_id)
        if action == "状态":
            enabled = bool(
                group_id in self._configured_daily_report_groups()
                or (group and group.daily_report_enabled)
            )
            state = "已开启" if enabled else "已关闭"
            self._reply_text(event, f"本群课表日报：{state}。")
            return
        if action not in {"开启", "关闭"}:
            self._reply_text(event, "可选：课表日报 开启 / 关闭 / 状态")
            return
        if not self._has_group_admins(group_id):
            self._reply_text(event, "请先在 WebUI 配置本群课表管理员。")
            return
        if not self._is_group_admin(group_id, event.get_sender_id()):
            self._reply_text(event, "只有本群课表管理员可以修改日报开关。")
            return
        enabled = action == "开启"
        try:
            self.storage.set_daily_report_enabled(
                self.groups,
                group_id=group_id,
                unified_msg_origin=event.unified_msg_origin,
                enabled=enabled,
            )
            self._sync_daily_report_group_config(group_id, enabled)
        except OSError as exc:
            logger.exception("保存课表日报设置失败: %s", exc)
            self._reply_text(event, "日报设置保存失败，请稍后再试。")
            return
        state = "开启" if enabled else "关闭"
        self._reply_text(event, f"已{state}本群课表日报。")

    async def _handle_recall_setting(self, event: AstrMessageEvent, text: str) -> None:
        group_id = event.get_group_id()
        if not group_id:
            self._reply_text(event, "课表撤回设置只能在群聊中使用。")
            return
        action_text = text.removeprefix("课表撤回").strip()
        if action_text in {"", "状态"}:
            upload_state = (
                "开启" if self._auto_recall_ics_uploads_enabled(group_id) else "关闭"
            )
            image_state = (
                "开启"
                if self._auto_recall_schedule_images_enabled(group_id)
                else "关闭"
            )
            self._reply_text(
                event,
                f"本群课表撤回：ICS 文件{upload_state}，查询图片{image_state}（{self._image_recall_seconds()} 秒）。",
            )
            return
        parts = action_text.split()
        if len(parts) != 2 or parts[0] not in {"文件", "上传", "图片"}:
            self._reply_text(
                event,
                "可选：课表撤回 状态 / 文件 开启 / 文件 关闭 / 文件 跟随配置 / 图片 开启 / 图片 关闭 / 图片 跟随配置",
            )
            return
        if not self._has_group_admins(group_id):
            self._reply_text(event, "请先在 WebUI 配置本群课表管理员。")
            return
        if not self._is_group_admin(group_id, event.get_sender_id()):
            self._reply_text(event, "只有本群课表管理员可以修改撤回开关。")
            return
        try:
            enabled = self._parse_recall_switch(parts[1])
        except ValueError:
            self._reply_text(event, "开关只能是：开启 / 关闭 / 跟随配置")
            return
        try:
            if parts[0] in {"文件", "上传"}:
                self.storage.set_auto_recall_ics_uploads(
                    self.groups,
                    group_id=group_id,
                    unified_msg_origin=event.unified_msg_origin,
                    enabled=enabled,
                )
                label = "ICS 文件"
            else:
                self.storage.set_auto_recall_schedule_images(
                    self.groups,
                    group_id=group_id,
                    unified_msg_origin=event.unified_msg_origin,
                    enabled=enabled,
                )
                label = "查询图片"
        except OSError as exc:
            logger.exception("保存课表撤回设置失败: %s", exc)
            self._reply_text(event, "撤回设置保存失败，请稍后再试。")
            return
        state = (
            "跟随 WebUI 配置" if enabled is None else ("开启" if enabled else "关闭")
        )
        self._reply_text(event, f"已设置本群{label}自动撤回：{state}。")

    def _parse_recall_switch(self, text: str) -> bool | None:
        if text == "开启":
            return True
        if text == "关闭":
            return False
        if text == "跟随配置":
            return None
        raise ValueError("invalid recall switch")

    async def _handle_delete(self, event: AstrMessageEvent) -> None:
        try:
            member = self.storage.delete_schedule(
                self.groups,
                group_id=event.get_group_id(),
                user_id=event.get_sender_id(),
            )
        except OSError as exc:
            logger.exception("删除课表绑定失败: %s", exc)
            self._reply_text(event, "课表删除失败，请稍后再试。")
            return
        self.recent_files.pop((event.get_group_id(), event.get_sender_id()), None)
        self.pending_binds.pop((event.get_group_id(), event.get_sender_id()), None)
        if not member:
            self._reply_text(event, "你还没有绑定课表。")
            return
        self._reply_text(event, "已删除你的课表绑定。")

    def _schedule_message_recall(
        self,
        event: AstrMessageEvent,
        message_id: str,
        delay_seconds: int,
    ) -> None:
        if event.get_platform_name() != "aiocqhttp" or not message_id:
            return
        self._schedule_onebot_recall(event.bot, message_id, delay_seconds)

    def _schedule_onebot_recall(
        self,
        bot: Any,
        message_id: str,
        delay_seconds: int,
    ) -> None:
        if not message_id:
            return
        task = asyncio.create_task(delayed_recall(bot, message_id, delay_seconds))
        self.recall_tasks.add(task)
        task.add_done_callback(self.recall_tasks.discard)

    async def _send_daily_reports(self) -> None:
        """Send scheduled group reports while isolating per-group failures."""

        today = datetime.now(self.timezone).date()
        for group in self.groups.values():
            if not self._daily_report_enabled(group):
                continue
            public_group = type(group)(
                group_id=group.group_id,
                unified_msg_origin=group.unified_msg_origin,
                members={
                    user_id: member
                    for user_id, member in group.members.items()
                    if member.privacy != PrivacyMode.PRIVATE
                },
                daily_report_enabled=group.daily_report_enabled,
            )
            if not public_group.unified_msg_origin:
                continue
            try:
                rows = self.service.daily_report(public_group, today)
                if not rows:
                    continue
                html = report_html(
                    public_group.group_id, datetime.now(self.timezone), rows
                )
                url = await self._render_image(html)
                await self.context.send_message(
                    public_group.unified_msg_origin, MessageChain().url_image(url)
                )
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.exception("发送课表日报失败 group=%s: %s", group.group_id, exc)
