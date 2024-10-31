import time
from pathlib import Path

from syftbox.client.plugins.apps import run as app_runner
from tests.integration.app_plugin.fixtures.app_mocks import AppMockFactory


def verify_app_execution(app_dir: Path, expected_output: str):
    """Verify app execution results."""
    app_log_path = app_dir / "app.log"
    assert app_log_path.exists()
    assert app_log_path.read_text().strip() == expected_output


def verify_running_apps(running_apps: dict, expected_app_name: str = None):
    """Verify running apps state."""
    if expected_app_name:
        assert len(running_apps) == 1
        assert expected_app_name in running_apps
    else:
        assert len(running_apps) == 0


def test_app_plugin_without_config(shared_state, test_client_config, monkeypatch):
    """Test app plugin execution without configuration."""
    apps_dir = test_client_config.sync_folder / "apps"
    mock_app_dir, expected_output = AppMockFactory.create_app_without_config(apps_dir=apps_dir, app_name="test_app")

    assert mock_app_dir.exists()

    # Patch necessary attributes
    PATCHED_RUNNING = {}
    monkeypatch.setattr("syftbox.client.plugins.apps.DEFAULT_APPS_PATH", "")
    monkeypatch.setattr("syftbox.client.plugins.apps.RUNNING_APPS", PATCHED_RUNNING)

    # Run app
    app_runner(shared_state=shared_state)

    # Verify results
    verify_running_apps(PATCHED_RUNNING)
    verify_app_execution(mock_app_dir, expected_output)


def test_app_plugin_with_config(shared_state, test_client_config, monkeypatch):
    """Test app plugin execution with configuration."""
    apps_dir = test_client_config.sync_folder / "apps"
    mock_app_dir, expected_output = AppMockFactory.create_app_with_config(apps_dir=apps_dir, app_name="test_app")

    assert mock_app_dir.exists()

    # Patch necessary attributes
    PATCHED_RUNNING = {}
    monkeypatch.setattr("syftbox.client.plugins.apps.DEFAULT_APPS_PATH", "")
    monkeypatch.setattr("syftbox.client.plugins.apps.RUNNING_APPS", PATCHED_RUNNING)

    # Run app
    app_runner(shared_state=shared_state)
    time.sleep(2)

    # Verify results
    verify_running_apps(PATCHED_RUNNING, "test_app")
    verify_app_execution(mock_app_dir, expected_output)

    # This doesn't kill the process gracefully,
    # later need to implement a graceful shutdown mechanism for apps
    PATCHED_RUNNING["test_app"].join(timeout=1)
