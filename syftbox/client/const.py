from pathlib import Path

DEFAULT_WORKSPACE_DIR = Path("~/Desktop/SyftBox").expanduser()
DEFAULT_CONFIG_DIR = DEFAULT_WORKSPACE_DIR / "config"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "client_config.json"

DEFAULT_PORT = 8082
SYFTBOX_SERVER_URL = "https://syftbox.openmined.org"
