# Handle configuratoin loading and management
import argparse
import os
import platform

from syftbox.lib import ClientConfig, validate_email
from icon import copy_icon_file
from const import DEFAULT_CONFIG_PATH, DEFAULT_SYNC_FOLDER, ICON_FOLDER, DEFAULT_PORT, DEFAULT_SERVER_URL


def get_user_input(prompt: str, default: str | None = None) -> str:
    if default:
        prompt = f"{prompt} (default: {default}): "
    user_input = input(prompt).strip()
    return user_input if user_input else default


# Parsing arguments and initializing shared state
def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the web application with plugins.",
    )
    parser.add_argument(
        "--config_path", type=str, default=DEFAULT_CONFIG_PATH, help="config path"
    )
    parser.add_argument(
        "--sync_folder", type=str, default=DEFAULT_SYNC_FOLDER, help="sync folder path"
    )
    parser.add_argument("--email", type=str, help="email")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port number")
    parser.add_argument(
        "--server",
        type=str,
        default=DEFAULT_SERVER_URL,
        help="Server",
    )
    return parser.parse_args()


def load_or_create_config(args) -> ClientConfig:
    client_config = None
    try:
        client_config = ClientConfig.load(args.config_path)
    except Exception:
        pass

    if client_config is None and args.config_path:
        config_path = os.path.abspath(os.path.expanduser(args.config_path))
        client_config = ClientConfig(config_path=config_path)

    if client_config is None:
        # config_path = get_user_input("Path to config file?", DEFAULT_CONFIG_PATH)
        config_path = os.path.abspath(os.path.expanduser(config_path))
        client_config = ClientConfig(config_path=config_path)

    if args.sync_folder:
        sync_folder = os.path.abspath(os.path.expanduser(args.sync_folder))
        client_config.sync_folder = sync_folder

    if client_config.sync_folder is None:
        sync_folder = get_user_input(
            "Where do you want to Sync SyftBox to?",
            DEFAULT_SYNC_FOLDER,
        )
        sync_folder = os.path.abspath(os.path.expanduser(sync_folder))
        client_config.sync_folder = sync_folder

    if args.server:
        client_config.server_url = args.server

    if not os.path.exists(client_config.sync_folder):
        os.makedirs(client_config.sync_folder, exist_ok=True)

    if platform.system() == "Darwin":
        copy_icon_file(ICON_FOLDER, client_config.sync_folder)

    if args.email:
        client_config.email = args.email

    if client_config.email is None:
        email = get_user_input("What is your email address? ")
        if not validate_email(email):
            raise Exception(f"Invalid email: {email}")
        client_config.email = email

    if args.port:
        client_config.port = args.port

    if client_config.port is None:
        port = int(get_user_input("Enter the port to use", DEFAULT_PORT))
        client_config.port = port

    email_token = os.environ.get("EMAIL_TOKEN", None)
    if email_token:
        client_config.email_token = email_token

    client_config.save(args.config_path)
    return client_config