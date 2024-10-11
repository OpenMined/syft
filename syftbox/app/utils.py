import os

config_path = os.environ.get(
    "SYFTBOX_CLIENT_CONFIG_PATH", os.path.expanduser("~/.syftbox/client_config.json")
)


def get_config_path() -> str:
    config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", None)
    if config_path is None:
        config_path = (
            str(
                input(
                    "Path to your syftbox config.json file (eg: /home/user/SyftBox/config/): "
                )
            )
            + "/"
        )
        os.environ["SYFTBOX_CLIENT_CONFIG_PATH"] = (
            config_path + "/"
        )  # Add a / just in case it's not passed.
    return config_path
