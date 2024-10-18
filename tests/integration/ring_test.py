import argparse
import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from syftbox.app.install import install
from syftbox.client.plugins.apps import run as run_apps
from syftbox.client.plugins.sync import do_sync
from syftbox.lib.lib import ClientConfig, SharedState


def mock_argparse_install_ring_app(*args, **kwargs):
    # Create a mock for the parsed arguments
    return argparse.Namespace(repository="https://github.com/OpenMined/ring")


def install_ring(client_config: ClientConfig, monkeypatch: MonkeyPatch):
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args", mock_argparse_install_ring_app
    )
    install(client_config)


def sync_datasites(datasites: list[ClientConfig]):
    # Round robin sync
    for datasite in datasites:
        do_sync(SharedState(client_config=datasite))

    for datasite in datasites[::-1]:
        do_sync(SharedState(client_config=datasite))


def apps_pipeline_for(datasite_config: ClientConfig, app_name: str, state: str) -> Path:
    return (
        Path(datasite_config.sync_folder)
        / datasite_config.email
        / "app_pipelines"
        / app_name
        / state
    )


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
                    "alice@openmined.org",
                ],
                "data": 3,
                "current_index": 3,
            },
        )
    ],
)
def test_syftbox_ring(
    monkeypatch: MonkeyPatch,
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
    sync_datasites([datasite_1, datasite_2])

    # time.sleep(20)

    datasite_1_sync_folder = Path(datasite_1.sync_folder)
    print("datasite_1_sync_folder", datasite_1_sync_folder)
    datasite_2_sync_folder = Path(datasite_2.sync_folder)
    print("datasite_2_sync_folder", datasite_2_sync_folder)

    datasite_1_running_dir = apps_pipeline_for(datasite_1, "ring", "running")
    datasite_2_running_dir = apps_pipeline_for(datasite_2, "ring", "running")

    # Create data in alice's datasite
    assert (
        datasite_1_running_dir.exists()
    ), f"Running directory does not exist {datasite_1_running_dir}"

    with open(datasite_1_running_dir / "data.json", "w") as fp:
        json.dump(input_json, fp)

    run_apps(datasite_1_shared_state)
    # ---------------------------------------------------------------

    sync_datasites([datasite_1, datasite_2])

    file_in_datasite_2 = datasite_2_running_dir / "data.json"

    assert file_in_datasite_2.exists(), f"File does not exist {file_in_datasite_2}"

    run_apps(datasite_2_shared_state)
    sync_datasites([datasite_1, datasite_2])

    # while True:
    #     datasite_1_done_dir = datasite_1_ring_app / "done"

    #     if datasite_1_done_dir.exists():
    #         actual_json_fp = datasite_1_done_dir / "data.json"
    #         assert json.loads(actual_json_fp.open()) == expected_json
    #         break

    #     time.sleep(5)

    #     if start_time - time.time() > 180:
    #         raise TimeoutError("Timedout")
