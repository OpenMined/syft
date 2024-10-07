import json
import os
from datetime import datetime

from syftbox.lib import ClientConfig


def main():
    # Load the client configuration
    config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", None)
    client_config = ClientConfig.load(config_path)

    # Get the current timestamp
    current_timestamp = datetime.now().isoformat()

    # Prepare the data to be written
    timestamp_data = {"last_check_in": current_timestamp}

    # Prepare output folders
    output_folder = f"{client_config.sync_folder}/{client_config.email}/app_pipelines/timestamp_recorder/"
    os.makedirs(output_folder, exist_ok=True)

    # Write timestamp to output file
    output_file_path = f"{output_folder}last_check_in.json"
    with open(output_file_path, "w") as f:
        json.dump(timestamp_data, f, indent=2)

    # Write _.syftperm file
    syftperm_data = {
        "admin": [client_config.email],
        "read": ["GLOBAL"],
        "write": [client_config.email],
        "filepath": f"{output_folder}_.syftperm",
        "terminal": False,
    }
    syftperm_path = f"{output_folder}_.syftperm"
    with open(syftperm_path, "w") as f:
        json.dump(syftperm_data, f, indent=2)

    print(f"Timestamp has been written to {output_file_path}")
    print(f"_.syftperm file has been written to {syftperm_path}")


if __name__ == "__main__":
    main()
