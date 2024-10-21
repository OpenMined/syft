import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from pytest import MonkeyPatch

from syftbox.app.install import install
from syftbox.client.plugins.apps import run as run_apps
from syftbox.client.plugins.sync import do_sync
from syftbox.lib.lib import ClientConfig, SharedState
from tests.conftest import setup_datasite

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


#TODO: Solve name confusion in the server client before merge
@pytest.mark.parametrize(
    "input_json,expected_json",
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
                "current_index": 2,
            },
        ),
        (
            {
                "ring": [
                    "alice@openmined.org",
                    "bob@openmined.org",
                    "charlie@openmined.org",
                    "alice@openmined.org"
                ],
                "data": 0,
                "current_index": 0,
            },
            {
                "ring": [
                    "alice@openmined.org",
                    "bob@openmined.org",
                    "charlie@openmined.org",
                    "alice@openmined.org"
                ],
                "data": 4,
                "current_index": 3,
            },
        )

    ],
)
def test_syftbox_ring_new(tmp_path: Path,server_client: TestClient, monkeypatch: MonkeyPatch, input_json: dict,expected_json: dict):
    # Create a generic test function for the ring app

    # Step 0: Create clients with the ring parties
    # Step 1: load data.json to the first person in the ring
    # Step 2: run the ring app and sync the datasites
    # Step 3: check the data.json in the next person in the ring in the running directory
    # Step 4: Repeat step 2 and 3 until the last person in the ring
    # Step 5: check the data.json for the last person in the done directory

    print(input_json, expected_json)

    ring_parties = input_json["ring"]
    datasites = []
    for email in ring_parties:
        datasites.append(setup_datasite(tmp_path, server_client, email))
        curr_datasite = datasites[-1]
        install_ring(curr_datasite, monkeypatch)
        run_apps(SharedState(client_config=curr_datasite))

    sync_datasites(datasites)

    # Copy the data.json to the first person in the ring
    datasite_1 = datasites[0]
    datasite_1_running_dir = apps_pipeline_for(datasite_1, "ring", "running")
    datasite_1_done_dir = apps_pipeline_for(datasite_1, "ring", "done")
    assert (
        datasite_1_running_dir.exists()
    ), f"Running directory does not exist {datasite_1_running_dir}"

    with open(datasite_1_running_dir / "data.json", "w") as fp:
        json.dump(input_json, fp)

    for idx in range(len(datasites)-1):
        curr_datasite = datasites[idx]
        next_datasite = datasites[idx+1]

        run_apps(SharedState(client_config=curr_datasite))
        sync_datasites(datasites)

        file_in_next_datasite = apps_pipeline_for(next_datasite, "ring", "running") / "data.json"
        assert file_in_next_datasite.exists(), f"File does not exist {file_in_next_datasite}"
        with file_in_next_datasite.open() as fp:
            data_in_next_datasite = json.load(fp)
        assert data_in_next_datasite["data"] == idx+1
        assert data_in_next_datasite["current_index"] == idx+1

    # Run the ring app again, sync the datasites. Data should be moved to last person's ring done dir
    run_apps(SharedState(client_config=datasites[-1]))
    sync_datasites(datasites)
    file_in_datasite_1 = datasite_1_done_dir / "data.json"
    assert file_in_datasite_1.exists(), f"File does not exist {file_in_datasite_1}"
    with file_in_datasite_1.open() as fp:
        data_in_datasite_1 = json.load(fp)
    assert data_in_datasite_1["data"] == expected_json["data"]
    assert data_in_datasite_1["current_index"] == expected_json["current_index"]
