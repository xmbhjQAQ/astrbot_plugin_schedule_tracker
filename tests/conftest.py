import logging
import sys
import types
from pathlib import Path


PACKAGE_NAME = "astrbot_plugin_schedule_tracker"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]

astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("schedule-tracker-test")
astrbot_event_module = types.ModuleType("astrbot.api.event")
astrbot_message_components_module = types.ModuleType("astrbot.api.message_components")


class AstrMessageEvent:
    pass


class File:
    def __init__(self, name: str = "", url: str = "", file: str = "") -> None:
        self.name = name
        self.url = url
        self.file_ = file

    async def get_file(self) -> str:
        return self.url or self.file_


astrbot_event_module.AstrMessageEvent = AstrMessageEvent
astrbot_message_components_module.File = File
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("astrbot.api.event", astrbot_event_module)
sys.modules.setdefault(
    "astrbot.api.message_components", astrbot_message_components_module
)

package_module = types.ModuleType(PACKAGE_NAME)
package_module.__path__ = [str(PACKAGE_ROOT)]
sys.modules.setdefault(PACKAGE_NAME, package_module)
