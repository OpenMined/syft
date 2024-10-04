import json
import os
from pathlib import Path

from syftbox.lib import ClientConfig

config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", None)
client_config = ClientConfig.load(config_path)

input_folder = Path(client_config.sync_folder) / client_config.email / "app_pipelines" / "adder" / "inputs"
output_folder = Path(client_config.sync_folder) / client_config.email / "app_pipelines" / "adder" / "done"
input_folder.mkdir(parents=True, exist_ok=True)
output_folder.mkdir(parents=True, exist_ok=True)

input_file_path = input_folder / "data.json"
output_file_path = output_folder / "data.json"

if input_file_path.exists():
    with input_file_path.open(mode="r") as f:
        data = json.load(f)

    data["datum"] += 1

    with output_file_path.open(mode="w") as f:
        json.dump(data, f)

    input_file_path.unlink()
else:
    print(f"Input file {input_file_path} does not exist.")
