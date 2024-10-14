from pathlib import Path

from syftbox.lib.workspace import SyftWorkspace

# Directories
CURRENT_DIR = Path(__file__).parent
PLUGINS_DIR = CURRENT_DIR / "plugins"
TEMPLATES_DIR = CURRENT_DIR / "templates"
ASSETS_FOLDER = CURRENT_DIR.parent / "assets"
ICON_FOLDER = ASSETS_FOLDER / "icon"

# SyftWorkspace related
DEFAULT_SYNC_FOLDER = SyftWorkspace().sync_dir
DEFAULT_CONFIG_PATH = SyftWorkspace().config_dir / "client_config.json"
DEFAULT_LOGS_PATH = SyftWorkspace().logs_dir / "syftbox.log"

# Network
DEFAULT_PORT = 8082
DEFAULT_SERVER_URL = "https://syftbox.openmined.org"

# Watchdog
WATCHDOG_IGNORE = ["apps"]

# Plugins
AUTORUN_PLUGINS = ["init", "create_datasite", "sync", "apps"]

# Other constants
DEFAULT_PLUGIN_SCHEDULE = 5000  # milliseconds
