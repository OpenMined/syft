import argparse
import os
import sys
from collections import namedtuple
from pathlib import Path

from loguru import logger

from ..lib import DEFAULT_CONFIG_PATH, ClientConfig
from .install import install

config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", None)


def list_app(client_config: ClientConfig, silent: bool = False) -> list[str]:
    apps_path = Path(client_config.sync_folder + "/" + "apps")
    apps = []
    if os.path.exists(apps_path):
        files_and_folders = os.listdir(apps_path)
        apps = [app for app in files_and_folders if os.path.isdir(apps_path / app)]

    if len(apps):
        if not silent:
            logger.info("\nInstalled apps:")
            for app in apps:
                logger.info(f"✅ {app}")
    else:
        if not silent:
            logger.info(
                "\nYou have no apps installed.\n\n"
                f"Try:\nsyftbox app install OpenMined/github_app_updater\n\nor copy an app to: {apps_path}"
            )
    return apps


def uninstall_app(client_config: ClientConfig) -> None:
    logger.info("Uninstalling Apps")


def update_app(client_config: ClientConfig) -> None:
    logger.info("Updating Apps")


def upgrade_app(client_config: ClientConfig) -> None:
    logger.info("Upgrading Apps")


Commands = namedtuple("Commands", ["description", "execute"])


def make_commands() -> dict[str, Commands]:
    return {
        "list": Commands(
            "List all currently installed apps in your syftbox.", list_app
        ),
        "install": Commands("Install a new app in your syftbox.", install),
        "uninstall": Commands("Uninstall a certain app.", uninstall_app),
        "update": Commands("Check for app updates.", update_app),
        "upgrade": Commands("Upgrade an app.", upgrade_app),
    }


class CustomHelpFormatter(argparse.HelpFormatter):
    def add_arguments(self, actions):
        for action in actions:
            if action.dest == "command":
                commands = make_commands()
                action.choices = commands.keys()
                # Build help message with descriptions
                action.help = "\n".join(
                    [f"{cmd}: {commands[cmd].description}" for cmd in commands]
                )
        super().add_arguments(actions)


# Parsing arguments and initializing shared state
def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the web application with plugins.",
    )

    commands = make_commands()

    # Add a subparser to the "app" parser to handle different actions
    parser.add_argument(
        "command", choices=commands.keys(), help="The command to execute"
    )

    parser.add_argument(
        "--config_path", type=str, default=DEFAULT_CONFIG_PATH, help="config path"
    )
    args, remaining_args = parser.parse_known_args()
    return args, remaining_args


def main(parser, args_list) -> None:
    args, remaining_args = parse_args()
    client_config = ClientConfig.load(args.config_path)

    commands = make_commands()
    # Handle the subcommands as needed
    if args.command:
        command = commands[args.command]
        sys.argv = [sys.argv[0]] + remaining_args
        result = command.execute(client_config)
        if result is not None:
            # we should make this a type
            if isinstance(result, tuple):
                step, exception = result
                logger.info(f"Error during {step}: ", str(exception))
    else:
        parser.print_help()
