from pathlib import Path
from syftbox.lib.workspace import SyftWorkspace


# Directories
CURRENT_DIR = Path(__file__).parent
PLUGINS_DIR = CURRENT_DIR / "plugins"
ASSETS_FOLDER = CURRENT_DIR.parent / "assets"
ICON_FOLDER = ASSETS_FOLDER / "icon"

# SyftWorkspace related
DEFAULT_SYNC_FOLDER = SyftWorkspace().sync_dir
DEFAULT_CONFIG_PATH = SyftWorkspace().config_dir / "client_config.json"

# Network
DEFAULT_PORT = 8082
DEFAULT_SERVER_URL = "http://syftbox.openmined.org:8080"

# Watchdog
WATCHDOG_IGNORE = ["apps"]

# Plugins
AUTORUN_PLUGINS = ["init", "create_datasite", "sync", "apps"]

# Other constants
DEFAULT_PLUGIN_SCHEDULE = 5000  # milliseconds