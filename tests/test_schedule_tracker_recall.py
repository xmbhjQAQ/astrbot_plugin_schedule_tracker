import asyncio

from astrbot_plugin_schedule_tracker.recall import (
    call_onebot_action,
    extract_message_id,
    onebot_image_segment,
    recall_message,
    send_group_image,
)


class _ApiClient:
    def __init__(self) -> None:
        self.calls = []

    async def call_action(self, action, **payload):
        self.calls.append((action, payload))
        return {"message_id": 123}


class _BotWithApi:
    def __init__(self) -> None:
        self.api = _ApiClient()


class _BotWithCallAction:
    def __init__(self) -> None:
        self.calls = []

    async def call_action(self, action, **payload):
        self.calls.append((action, payload))
        return {"id": "abc"}


def test_onebot_image_segment_uses_image_file_payload():
    assert onebot_image_segment("http://image") == [
        {"type": "image", "data": {"file": "http://image"}}
    ]


def test_extract_message_id_supports_common_response_shapes():
    assert extract_message_id({"message_id": 123}) == "123"
    assert extract_message_id({"id": "abc"}) == "abc"


def test_call_onebot_action_prefers_api_client():
    bot = _BotWithApi()

    result = asyncio.run(call_onebot_action(bot, "delete_msg", message_id="1"))

    assert result == {"message_id": 123}
    assert bot.api.calls == [("delete_msg", {"message_id": "1"})]


def test_send_group_image_returns_message_id():
    bot = _BotWithCallAction()

    message_id = asyncio.run(send_group_image(bot, "100", "http://image"))

    assert message_id == "abc"
    assert bot.calls == [
        (
            "send_group_msg",
            {
                "group_id": 100,
                "message": [{"type": "image", "data": {"file": "http://image"}}],
            },
        )
    ]


def test_recall_message_skips_empty_message_id():
    bot = _BotWithCallAction()

    asyncio.run(recall_message(bot, ""))

    assert bot.calls == []
