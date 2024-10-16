
from pathlib import Path

import pytest
import json
import time


@pytest.fixture(scope="function")
def client_1() -> Path:
    root_dir = Path(__file__).parent.parent.parent

    client_1_sync_path = root_dir / ".clients" / "alice@openmined.org" / "sync"

    if not client_1_sync_path.exists():
        raise Exception("Client 1 sync path does not exist")

    return client_1_sync_path

@pytest.fixture(scope="function")
def client_2() -> Path:
    root_dir = Path(__file__).parent.parent.parent

    client_2_sync_path = root_dir / ".clients" / "bob@openmined.org" / "sync"

    if not client_2_sync_path.exists():
        raise Exception("Client 2 sync path does not exist")

    return client_2_sync_path


# client_1: points to sync directory of alice@openmined.org
# client_2: points to sync directory of bob@openmined.org
@pytest.mark.parametrize(
        "data_json", [
            (
            {
                "ring": ["alice@openmined.org","bob@openmined.org", "alice@openmined.org"],
                "data": 0,
                "current_index":0
            },
            {
                "ring": ["alice@openmined.org","bob@openmined.org", "alice@openmined.org"],
                "data": 3,
                "current_index":3
            }
            )
        ]
)
def test_syftbox_ring(client_1: Path, client_2: Path, data_json):
    
    input_json, expected_json = data_json

    client_1_ring_app = client_1 / "app_pipelines" / "ring"
    client_1_running_dir = client_1_ring_app / "running"

    assert client_1_running_dir.exists() , f"Running directory does not exist {client_1_running_dir}"
    
    with open(client_1_running_dir / "data.json", "w" ) as fp:
        json.dump(input_json, fp)

    
    start_time = time.time()
    

    while(True):
        client_1_done_dir = client_1_ring_app / "done"
        
        if client_1_done_dir.exists():
            actual_json_fp = client_1_done_dir / "data.json"
            assert json.loads(actual_json_fp.open()) == expected_json
            break

        time.sleep(5)

        if start_time - time.time() > 180:
            raise TimeoutError("Timedout")


    
    
