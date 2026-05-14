"""Persistence helpers for schedule tracker state.

All files live under AstrBot's data/plugin_data directory, not inside the plugin
source tree. That keeps user schedules intact when the plugin is updated or
reinstalled.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astrbot.api import logger

from .models import GroupState, PrivacyMode, ScheduleMember


class ScheduleStorage:
    """Stores group state metadata and copied ICS files on disk."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.schedules_dir = data_dir / "schedules"
        self.state_path = data_dir / "state.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.schedules_dir.mkdir(parents=True, exist_ok=True)

    def load_groups(self) -> dict[str, GroupState]:
        """Load persisted state, skipping damaged records instead of crashing."""

        if not self.state_path.exists():
            return {}
        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("课表状态文件读取失败，将以空状态启动: %s", exc)
            return {}
        groups: dict[str, GroupState] = {}
        if not isinstance(raw, dict):
            logger.warning("课表状态文件结构无效，将以空状态启动。")
            return {}

        # The state file is user data. Be conservative when reading it: a manual
        # edit or interrupted write should not prevent the plugin from loading.
        raw_groups = raw.get("groups", {})
        if not isinstance(raw_groups, dict):
            logger.warning("课表状态文件 groups 字段无效，将以空状态启动。")
            return {}
        for group_id, group_raw in raw_groups.items():
            if not isinstance(group_raw, dict):
                logger.warning("跳过无效课表群状态 group=%s。", group_id)
                continue
            members = {}
            raw_members = group_raw.get("members", {})
            if not isinstance(raw_members, dict):
                raw_members = {}
            for user_id, member_raw in raw_members.items():
                try:
                    members[user_id] = ScheduleMember(
                        group_id=group_id,
                        user_id=user_id,
                        display_name=member_raw.get("display_name") or user_id,
                        privacy=PrivacyMode(
                            member_raw.get("privacy", PrivacyMode.PUBLIC.value)
                        ),
                        ics_path=member_raw["ics_path"],
                        bound_at=member_raw.get("bound_at", ""),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    # 一个成员的历史数据损坏不应阻止整个插件加载。
                    logger.warning(
                        "跳过无效课表成员状态 group=%s user=%s: %s",
                        group_id,
                        user_id,
                        exc,
                    )
            groups[group_id] = GroupState(
                group_id=group_id,
                unified_msg_origin=group_raw.get("unified_msg_origin", ""),
                members=members,
                daily_report_enabled=bool(group_raw.get("daily_report_enabled", False)),
                auto_recall_ics_uploads=group_raw.get("auto_recall_ics_uploads"),
                auto_recall_schedule_images=group_raw.get(
                    "auto_recall_schedule_images"
                ),
            )
        return groups

    def save_groups(self, groups: dict[str, GroupState]) -> None:
        """Atomically write state metadata to reduce corruption on interruption."""

        raw = {"groups": {}}
        for group_id, group in groups.items():
            raw["groups"][group_id] = {
                "unified_msg_origin": group.unified_msg_origin,
                "daily_report_enabled": group.daily_report_enabled,
                "auto_recall_ics_uploads": group.auto_recall_ics_uploads,
                "auto_recall_schedule_images": group.auto_recall_schedule_images,
                "members": {
                    user_id: {
                        "display_name": member.display_name,
                        "privacy": member.privacy.value,
                        "ics_path": member.ics_path,
                        "bound_at": member.bound_at,
                    }
                    for user_id, member in group.members.items()
                },
            }
        tmp_path = self.state_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self.state_path)

    def bind_schedule(
        self,
        groups: dict[str, GroupState],
        *,
        group_id: str,
        unified_msg_origin: str,
        user_id: str,
        display_name: str,
        source_path: str,
        timezone: ZoneInfo,
    ) -> ScheduleMember:
        """Copy an ICS file into plugin data and register it for the member."""

        group = groups.setdefault(
            group_id,
            GroupState(
                group_id=group_id, unified_msg_origin=unified_msg_origin, members={}
            ),
        )
        group.unified_msg_origin = unified_msg_origin

        target_dir = self.schedules_dir / group_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{user_id}.ics"
        shutil.copyfile(source_path, target_path)

        previous = group.members.get(user_id)
        member = ScheduleMember(
            group_id=group_id,
            user_id=user_id,
            display_name=display_name
            or (previous.display_name if previous else user_id),
            privacy=previous.privacy if previous else PrivacyMode.PUBLIC,
            ics_path=str(target_path),
            bound_at=datetime.now(timezone).isoformat(),
        )
        group.members[user_id] = member
        self.save_groups(groups)
        return member

    def set_daily_report_enabled(
        self,
        groups: dict[str, GroupState],
        *,
        group_id: str,
        unified_msg_origin: str,
        enabled: bool,
    ) -> GroupState:
        """Persist the daily report switch for one group."""

        group = groups.setdefault(
            group_id,
            GroupState(
                group_id=group_id, unified_msg_origin=unified_msg_origin, members={}
            ),
        )
        group.unified_msg_origin = unified_msg_origin
        group.daily_report_enabled = enabled
        self.save_groups(groups)
        return group

    def set_auto_recall_ics_uploads(
        self,
        groups: dict[str, GroupState],
        *,
        group_id: str,
        unified_msg_origin: str,
        enabled: bool | None,
    ) -> GroupState:
        """Persist the group override for uploaded ICS message recall."""

        group = groups.setdefault(
            group_id,
            GroupState(
                group_id=group_id, unified_msg_origin=unified_msg_origin, members={}
            ),
        )
        group.unified_msg_origin = unified_msg_origin
        group.auto_recall_ics_uploads = enabled
        self.save_groups(groups)
        return group

    def set_auto_recall_schedule_images(
        self,
        groups: dict[str, GroupState],
        *,
        group_id: str,
        unified_msg_origin: str,
        enabled: bool | None,
    ) -> GroupState:
        """Persist the group override for schedule image recall."""

        group = groups.setdefault(
            group_id,
            GroupState(
                group_id=group_id, unified_msg_origin=unified_msg_origin, members={}
            ),
        )
        group.unified_msg_origin = unified_msg_origin
        group.auto_recall_schedule_images = enabled
        self.save_groups(groups)
        return group

    def set_privacy(
        self,
        groups: dict[str, GroupState],
        *,
        group_id: str,
        user_id: str,
        privacy: PrivacyMode,
    ) -> ScheduleMember | None:
        """Update a member privacy mode while preserving their bound schedule."""

        member = groups.get(group_id, GroupState(group_id, "", {})).members.get(user_id)
        if not member:
            return None
        member.privacy = privacy
        self.save_groups(groups)
        return member

    def delete_schedule(
        self,
        groups: dict[str, GroupState],
        *,
        group_id: str,
        user_id: str,
    ) -> ScheduleMember | None:
        """Remove a member binding and best-effort delete its copied ICS file."""

        group = groups.get(group_id)
        if not group:
            return None
        member = group.members.pop(user_id, None)
        if not member:
            return None
        try:
            if member.ics_path and os.path.exists(member.ics_path):
                os.remove(member.ics_path)
        except OSError:
            # Metadata removal is more important than failing the whole command
            # because a stale file could not be deleted.
            pass
        self.save_groups(groups)
        return member
