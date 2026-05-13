from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import GroupState, PrivacyMode, ScheduleMember


class ScheduleStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.schedules_dir = data_dir / "schedules"
        self.state_path = data_dir / "state.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.schedules_dir.mkdir(parents=True, exist_ok=True)

    def load_groups(self) -> dict[str, GroupState]:
        if not self.state_path.exists():
            return {}
        with self.state_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        groups: dict[str, GroupState] = {}
        for group_id, group_raw in raw.get("groups", {}).items():
            members = {}
            for user_id, member_raw in group_raw.get("members", {}).items():
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
            groups[group_id] = GroupState(
                group_id=group_id,
                unified_msg_origin=group_raw.get("unified_msg_origin", ""),
                members=members,
            )
        return groups

    def save_groups(self, groups: dict[str, GroupState]) -> None:
        raw = {"groups": {}}
        for group_id, group in groups.items():
            raw["groups"][group_id] = {
                "unified_msg_origin": group.unified_msg_origin,
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
        group = groups.setdefault(
            group_id,
            GroupState(group_id=group_id, unified_msg_origin=unified_msg_origin, members={}),
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
            display_name=display_name or (previous.display_name if previous else user_id),
            privacy=previous.privacy if previous else PrivacyMode.PUBLIC,
            ics_path=str(target_path),
            bound_at=datetime.now(timezone).isoformat(),
        )
        group.members[user_id] = member
        self.save_groups(groups)
        return member

    def set_privacy(
        self,
        groups: dict[str, GroupState],
        *,
        group_id: str,
        user_id: str,
        privacy: PrivacyMode,
    ) -> ScheduleMember | None:
        member = groups.get(group_id, GroupState(group_id, "", {})).members.get(user_id)
        if not member:
            return None
        member.privacy = privacy
        self.save_groups(groups)
        return member
