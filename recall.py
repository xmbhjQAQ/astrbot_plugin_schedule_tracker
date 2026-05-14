"""Best-effort message recall helpers for QQ/OneBot.

AstrBot's normal ``event.set_result(...)`` path does not expose the platform
message ID after sending.  Auto recall therefore has to use the aiocqhttp
OneBot API directly when the feature is enabled.  Unsupported platforms simply
fall back to the normal send path in ``main.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger


def onebot_image_segment(url: str) -> list[dict[str, dict[str, str] | str]]:
    """Build a minimal OneBot image message payload."""

    return [{"type": "image", "data": {"file": url}}]


def extract_message_id(response: Any) -> str:
    """Extract a OneBot message ID from common adapter response shapes."""

    if isinstance(response, dict):
        value = response.get("message_id") or response.get("id")
        return str(value) if value else ""
    value = getattr(response, "message_id", None) or getattr(response, "id", None)
    return str(value) if value else ""


async def call_onebot_action(bot: Any, action: str, **payload: Any) -> Any:
    """Call an aiocqhttp action across the two client styles used in examples."""

    api = getattr(bot, "api", None)
    call_action = getattr(api, "call_action", None)
    if callable(call_action):
        return await call_action(action, **payload)
    call_action = getattr(bot, "call_action", None)
    if callable(call_action):
        return await call_action(action, **payload)
    raise RuntimeError("当前平台对象不支持 OneBot call_action")


async def send_group_image(bot: Any, group_id: str, image_url: str) -> str:
    """Send one group image through OneBot and return its platform message ID."""

    if not group_id.isdigit():
        raise ValueError(f"无效群号: {group_id}")
    response = await call_onebot_action(
        bot,
        "send_group_msg",
        group_id=int(group_id),
        message=onebot_image_segment(image_url),
    )
    return extract_message_id(response)


async def recall_message(bot: Any, message_id: str) -> None:
    """Recall one OneBot message if a message ID is available."""

    if not message_id:
        return
    await call_onebot_action(bot, "delete_msg", message_id=message_id)


async def delayed_recall(bot: Any, message_id: str, delay_seconds: int) -> None:
    """Recall after a delay, swallowing platform errors so tasks do not leak."""

    try:
        await asyncio.sleep(delay_seconds)
        await recall_message(bot, message_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("自动撤回消息失败 message_id=%s: %s", message_id, exc)
