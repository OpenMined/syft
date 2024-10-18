import json
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from fastapi.testclient import TestClient
import pytest
from syftbox.app.install import  install

from syftbox.lib.lib import ClientConfig, SharedState
from syftbox.client.plugins.apps import run as run_apps
from pytest import MonkeyPatch
import argparse


def mock_argparse_install_ring_app(*args, **kwargs):
    # Create a mock for the parsed arguments
    return argparse.Namespace(repository="https://github.com/OpenMined/ring")

def install_ring(client_config: ClientConfig, monkeypatch: MonkeyPatch):
    monkeypatch.setattr('argparse.ArgumentParser.parse_args', mock_argparse_install_ring_app)
    install(client_config)



@pytest.mark.parametrize(
    "data_json",
    [
        (
            {
                "ring": [
                    "alice@openmined.org",
                    "bob@openmined.org",
                    "alice@openmined.org",
                ],
                "data": 0,
                "current_index": 0,
            },
            {
                "ring": [
                    "alice@openmined.org",
                    "bob@openmined.org",
                    "alice@openmined.org"
                ],
                "data": 3,
                "current_index": 3,
            },
        )
    ],
)
def test_syftbox_ring(
    monkeypatch: MonkeyPatch,
    server_client: TestClient, 
    datasite_1: ClientConfig, 
    datasite_2: ClientConfig, 
    data_json: tuple,
):
    input_json, expected_json = data_json

    print(input_json, expected_json)

    datasite_1_shared_state = SharedState(client_config=datasite_1)
    datasite_2_shared_state = SharedState(client_config=datasite_2)

    print()
    install_ring(datasite_1, monkeypatch)
    install_ring(datasite_2, monkeypatch)
    run_apps(datasite_1_shared_state)
    run_apps(datasite_2_shared_state)
    
    
    client_1_sync_folder = Path(datasite_1.sync_folder)
    print("client_1_sync_folder", client_1_sync_folder)
    client_2_sync_folder = Path(datasite_2.sync_folder)
    print("client_2_sync_folder", client_2_sync_folder)
    print("Waiting")
    time.sleep(20)
    print("Done waiting")
    # client_1_ring_app_pipelines = datasite_1 / "app_pipelines"
    # client_1_running_dir = client_1_ring_app / "running"

    # assert (
    #     client_1_running_dir.exists()
    # ), f"Running directory does not exist {client_1_running_dir}"

    # with open(client_1_running_dir / "data.json", "w") as fp:
    #     json.dump(input_json, fp)

    # start_time = time.time()

    # while True:
    #     client_1_done_dir = client_1_ring_app / "done"

    #     if client_1_done_dir.exists():
    #         actual_json_fp = client_1_done_dir / "data.json"
    #         assert json.loads(actual_json_fp.open()) == expected_json
    #         break

    #     time.sleep(5)

    #     if start_time - time.time() > 180:
    #         raise TimeoutError("Timedout")
