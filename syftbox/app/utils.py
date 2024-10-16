import os

config_path = os.environ.get(
    "SYFTBOX_CLIENT_CONFIG_PATH", os.path.expanduser("~/.syftbox/client_config.json")
)

