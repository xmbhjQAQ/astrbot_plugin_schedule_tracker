import logging
import sys
import types
from pathlib import Path


PACKAGE_NAME = "astrbot_plugin_schedule_tracker"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]

astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("schedule-tracker-test")
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)

package_module = types.ModuleType(PACKAGE_NAME)
package_module.__path__ = [str(PACKAGE_ROOT)]
sys.modules.setdefault(PACKAGE_NAME, package_module)
