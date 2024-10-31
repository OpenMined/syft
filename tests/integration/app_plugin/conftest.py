# conftest.py
import shutil
import tempfile

import pytest

from syftbox.client.client import ClientConfig
from syftbox.lib.lib import SharedState
from syftbox.lib.workspace import SyftWorkspace


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    temp_root_dir = tempfile.mkdtemp()
    workspace = SyftWorkspace(temp_root_dir)
    workspace.mkdirs()

    yield workspace
    shutil.rmtree(workspace.root_dir)


@pytest.fixture
def test_client_config(temp_workspace):
    """Create a test client configuration with temporary directories."""
    config_path = temp_workspace.config_dir / "config.json"

    config = ClientConfig(
        email="test@example.com",
        config_path=config_path,
        sync_folder=temp_workspace.sync_dir,
        autorun_plugins=["apps"],
    )

    yield config


@pytest.fixture
def shared_state(test_client_config):
    """Create shared state for testing."""
    return SharedState(client_config=test_client_config)
