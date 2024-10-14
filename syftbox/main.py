import argparse
import sys

from loguru import logger

from syftbox import __version__
from syftbox.app.manager import list_app
from syftbox.app.manager import main as app_manager_main
from syftbox.client.client import main as client_main
from syftbox.server.server import main as server_main


def print_debug():
    try:
        import os
        import platform
        import shutil

        import psutil
        import yaml

        from syftbox.lib import DEFAULT_CONFIG_PATH, ClientConfig

        config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", DEFAULT_CONFIG_PATH)
        client_config = None
        apps = []
        try:
            client_config = ClientConfig.load(config_path)
            apps = list_app(client_config, silent=True)
            client_config = client_config.to_dict()
        except Exception:
            pass

        syftbox_path = shutil.which("syftbox")

        debug_info = {
            "system": {
                "resources": {
                    "cpus": psutil.cpu_count(logical=True),
                    "architecture": platform.machine(),
                    "ram": f"{psutil.virtual_memory().total / (1024**3):.2f} GB",
                },
                "operating_system": {
                    "name": "macOS"
                    if platform.system() == "Darwin"
                    else platform.system(),
                    "version": platform.release(),
                },
                "python": {
                    "version": platform.python_version(),
                    "binary_location": sys.executable,
                },
            },
            "syftbox": {
                "command": syftbox_path or "syftbox executable not found in PATH",
                "apps": apps,
                "client_config_path": config_path,
                "client_config": client_config,
            },
            "syftbox_env": {
                key: value
                for key, value in os.environ.items()
                if key.startswith("SYFT")
            },
        }
        logger.info(yaml.dump(debug_info, default_flow_style=False))
    except Exception as e:
        logger.info(e)


def main():
    parser = argparse.ArgumentParser(description="Syftbox CLI")
    subparsers = parser.add_subparsers(
        dest="command",
        description="Valid syftbox commands",
        help="subcommand to run",
    )

    # Define the client command
    subparsers.add_parser("client", help="Run the Syftbox client")

    # Define the server command
    subparsers.add_parser("server", help="Run the Syftbox server")

    # Define the install
    app_parser = subparsers.add_parser(
        "app", help="Manage SyftBox apps.", description="Manages SyftBox Apps"
    )

    app_parser = subparsers.add_parser(
        "version", help="Show SyftBox version", description="Shows the version"
    )

    app_parser = subparsers.add_parser(
        "debug", help="Show SyftBox debug info", description="Shows the debug info"
    )

    args, remaining_args = parser.parse_known_args()

    if args.command == "client":
        # Modify sys.argv to exclude the subcommand
        sys.argv = [sys.argv[0]] + remaining_args
        client_main()
    elif args.command == "server":
        # Modify sys.argv to exclude the subcommand
        sys.argv = [sys.argv[0]] + remaining_args
        server_main()
    elif args.command == "app":
        sys.argv = [sys.argv[0]] + remaining_args
        app_manager_main(app_parser, remaining_args)
    elif args.command == "version":
        print(__version__)
    elif args.command == "debug":
        logger.info_debug()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
