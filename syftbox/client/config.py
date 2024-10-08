# Handle configuratoin loading and management
import argparse
import os
import platform
from pathlib import Path

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
    try:
        config_path = Path(args.config_path).expanduser().resolve()
        print(f"Load and save configurations to {config_path}")
        # Create an empty JSON file if it doesn't exist
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                f.write('{}')
            print(f"Created empty JSON config file at {config_path}")
        client_config = ClientConfig(config_path=str(config_path))
        client_config = ClientConfig.load(str(config_path))
    except Exception as e:
        print(f"Error: {e}")

    try:
        sync_folder = Path(args.sync_folder).expanduser().resolve()
        client_config.sync_folder = str(sync_folder)
        print(f"Sync folder: {sync_folder}")
    except Exception as e:
        raise Exception(f"Error constructing sync folder: {e}")

    client_config.server_url = args.server
    print(f"Server: {client_config.server_url}")

    if platform.system() == "Darwin":
        copy_icon_file(ICON_FOLDER, client_config.sync_folder)

    if args.email:
        client_config.email = args.email

    if client_config.email is None:
        email = get_user_input("What is your email address? ")
        if not validate_email(email):
            raise Exception(f"Invalid email: {email}")
        client_config.email = email

    client_config.port = args.port

    email_token = os.environ.get("EMAIL_TOKEN", None)
    if email_token:
        client_config.email_token = email_token
    client_config.save(str(config_path))
    print(f"Save configurations to {config_path}")
    return client_config