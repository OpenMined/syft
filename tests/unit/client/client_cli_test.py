from pathlib import Path

from typer.testing import CliRunner

from syftbox.client.cli import app as client_cli

# Initialize test runner
runner = CliRunner()


def test_client_success(monkeypatch, mock_config):
    def setup_config_interactive(*args, **kwargs):
        return mock_config

    def mock_run_client(*args, **kwargs):
        return 0

    monkeypatch.setattr("syftbox.client.cli.run_client", mock_run_client)
    monkeypatch.setattr("syftbox.client.cli.setup_config_interactive", setup_config_interactive)

    result = runner.invoke(client_cli)
    assert result.exit_code == 0


def test_client_error(monkeypatch, mock_config):
    def setup_config_interactive(*args, **kwargs):
        return mock_config

    def mock_run_client(*args, **kwargs):
        return -1

    monkeypatch.setattr("syftbox.client.cli.run_client", mock_run_client)
    monkeypatch.setattr("syftbox.client.cli.setup_config_interactive", setup_config_interactive)

    result = runner.invoke(client_cli)
    assert result.exit_code == -1


def test_port_error(monkeypatch):
    monkeypatch.setattr("syftbox.client.cli.is_port_in_use", lambda p: True)
    result = runner.invoke(client_cli)
    assert result.exit_code == 1


def test_client_report(monkeypatch, tmp_path):
    monkeypatch.setattr("syftbox.lib.logger.zip_logs", lambda p, **kw: Path(str(p) + ".log"))
    result = runner.invoke(client_cli, ["report"])
    assert result.exit_code == 0
    assert "Logs saved at: " in result.stdout
