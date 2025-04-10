import signal
import sys
from pathlib import Path
from typing import Any

from click.core import ParameterSource
import httpx
from loguru import logger
from rich import print as rprint
from typer import Context, Exit, Option, Typer
from typing_extensions import Annotated, Optional

from syftbox.client.auth import authenticate_user
from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.constants import (
    DEFAULT_BENCHMARK_RUNS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_PORT,
    DEFAULT_SERVER_URL,
)
from syftbox.lib.http import HEADER_SYFTBOX_USER, SYFTBOX_HEADERS

app = Typer(
    name="SyftBox Client",
    pretty_exceptions_enable=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Define options separately to keep the function signature clean
# fmt: off

# client commands opts
CLIENT_PANEL = "Client Options"
LOCAL_SERVER_PANEL = "Local Server Options"

EMAIL_OPTS = Option(
    "-e", "--email",
    rich_help_panel=CLIENT_PANEL,
    help="Email for the SyftBox datasite",
)
SERVER_OPTS = Option(
    "-s", "--server",
    rich_help_panel=CLIENT_PANEL,
    help="SyftBox cache server URL",
)
DATA_DIR_OPTS = Option(
    "-d", "--data-dir", "--sync_folder",
    rich_help_panel=CLIENT_PANEL,
    help="Directory where SyftBox stores data",
)
CONFIG_OPTS = Option(
    "-c", "--config", "--config_path",
    rich_help_panel=CLIENT_PANEL,
    help="Path to SyftBox configuration file",
)
OPEN_OPTS = Option(
    is_flag=True,
    rich_help_panel=CLIENT_PANEL,
    help="Open SyftBox sync/data dir folder on client start",
)
PORT_OPTS = Option(
    "-p", "--port",
    rich_help_panel=LOCAL_SERVER_PANEL,
    help="Local port for the SyftBox client",
)
RELOAD_OPTS = Option(
    rich_help_panel=LOCAL_SERVER_PANEL,
    help="Run server in hot reload. Should not see this in production",
)
VERBOSE_OPTS = Option(
    "-v", "--verbose",
    is_flag=True,
    help="Enable verbose mode",
)
SERVICE_OPTS = Option(
    is_flag=True,
    help="Launch syftbox client with container-friendly defaults. Only read environment variables, ignoring existing config file or other inputs",
)


TOKEN_OPTS = Option(
    "--token",
    help="Token for password reset",
)

# report command opts
REPORT_PATH_OPTS = Option(
    "-o", "--output-dir",
    help="Directory to save the report file",
)

# benchmark command opts
JSON_BENCHMARK_REPORT_OPTS = Option(
    "--json", "-j",
    help="Path where benchmark report will be stored in JSON format",
)

# fmt: on


@app.callback(invoke_without_command=True)
def client(
    ctx: Context,
    data_dir: Annotated[Path, DATA_DIR_OPTS] = DEFAULT_DATA_DIR,
    email: Annotated[str, EMAIL_OPTS] = "",
    server: Annotated[str, SERVER_OPTS] = DEFAULT_SERVER_URL,
    config_path: Annotated[Path, CONFIG_OPTS] = DEFAULT_CONFIG_PATH,
    port: Annotated[int, PORT_OPTS] = DEFAULT_PORT,
    open_dir: Annotated[bool, OPEN_OPTS] = True,
    verbose: Annotated[bool, VERBOSE_OPTS] = False,
    service: Annotated[bool, SERVICE_OPTS] = False,
) -> None:
    """Run the SyftBox client"""

    if ctx.invoked_subcommand is not None:
        # If a subcommand is being invoked, just return
        return

    # If the service flag is set, run syftbox in service mode
    if service:
        setup_service_mode(ctx, verbose=verbose)
        return

    # lazy import to imporve cli startup speed
    from syftbox.client.core import run_syftbox
    from syftbox.client.setup_interactive import (
        get_migration_decision,
        setup_config_interactive,
    )
    from syftbox.client.utils.net import get_free_port, is_port_in_use

    if port == 0:
        port = get_free_port()
    elif is_port_in_use(port):
        # new_port = get_free_port()
        # port = new_port
        rprint(
            f"[bold red]Error:[/bold red] Client cannot start because port {port} is already in use!"
        )
        raise Exit(1)

    client_config = setup_config_interactive(config_path, email, data_dir, server, port)
    migrate_datasite = get_migration_decision(client_config.data_dir)

    log_level = "DEBUG" if verbose else "INFO"
    code = run_syftbox(
        client_config=client_config,
        open_dir=open_dir,
        log_level=log_level,
        migrate_datasite=migrate_datasite,
    )
    raise Exit(code)


def _setup_signal_handlers() -> None:
    """Set up signal handlers for graceful shutdown in container environments"""

    def handle_sigterm(sig: int, frame: Any) -> None:
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)


def setup_service_mode(
    ctx: Context, verbose: Annotated[bool, VERBOSE_OPTS] = False
) -> None:
    """
    Run SyftBox client in non-interactive mode using environment variables.

    This mode is designed for automation, containers, and services where
    configuration is provided through environment variables rather than
    interactive or a config file.

    Required environment variables:
    - SYFTBOX_CLIENT_CONFIG_PATH: Config file location (default: SYFTBOX_DATA_DIR/config.json)
    - SYFTBOX_EMAIL: Email for authentication
    - SYFTBOX_ACCESS_TOKEN: Authentication token

    Optional environment variables:
    - SYFTBOX_DATA_DIR: Data storage directory (default: ~/SyftBox)
    - SYFTBOX_SERVER_URL: SyftBox server URL
    - SYFTBOX_PORT: Port for local service (default: 8000)
    - SYFTBOX_CLIENT_TIMEOUT: Timeout for client connection to the server (default: 5)
    """
    for name, source in ctx._parameter_source.items():
        if name not in ("verbose", "service") and source == ParameterSource.COMMANDLINE:
            rprint(
                "[red]Error:[/red] Cannot use command line arguments when --service flag is set."
            )
            raise Exit(1)

    from syftbox.client.core import run_syftbox

    _setup_signal_handlers()

    client_config = SyftClientConfig.from_env(ignore_existing_config=True)
    config_dict = client_config.model_dump(mode="json", exclude=["access_token"])
    logger.info(
        "Running SyftBox client with config:\n"
        + "\n".join(f"{k}: {v}" for k, v in config_dict.items())
    )

    if client_config.access_token is None:
        login_client = httpx.Client(
            base_url=str(client_config.server_url),
            headers={
                **SYFTBOX_HEADERS,
                HEADER_SYFTBOX_USER: client_config.email,
            },
            transport=httpx.HTTPTransport(retries=10),
        )
        client_config.access_token = authenticate_user(client_config, login_client)
        # raise ValueError(
        #     "Cannot launch SyftBox in non-interactive mode without authentication. "
        #     "Please provide an access token via the SYFTBOX_ACCESS_TOKEN environment variable."
        # )

    log_level = "DEBUG" if verbose else "INFO"
    exit_code = run_syftbox(
        client_config=client_config,
        open_dir=False,
        log_level=log_level,
        migrate_datasite=True,
    )
    raise Exit(exit_code)


@app.command()
def report(
    output_path: Annotated[Path, REPORT_PATH_OPTS] = Path(".").resolve(),
    config_path: Annotated[Path, CONFIG_OPTS] = DEFAULT_CONFIG_PATH,
) -> None:
    """Generate a report of the SyftBox client"""
    from datetime import datetime

    from syftbox.client.logger import zip_logs
    from syftbox.lib.client_config import SyftClientConfig

    try:
        config = SyftClientConfig.load(config_path)
        name = f"syftbox_logs_{datetime.now().strftime('%Y_%m_%d_%H%M')}"
        output_path = Path(output_path, name).resolve()
        output_path_with_extension = zip_logs(
            output_path, log_dir=config.data_dir / "logs"
        )
        rprint(f"Logs from {config.data_dir} saved at {output_path_with_extension}.")
    except Exception as e:
        rprint(f"[red]Error[/red]: {e}")
        raise Exit(1)


@app.command()
def benchmark(
    config_path: Annotated[Path, CONFIG_OPTS] = DEFAULT_CONFIG_PATH,
    json: Annotated[Optional[Path], JSON_BENCHMARK_REPORT_OPTS] = None,
    num_runs: int = DEFAULT_BENCHMARK_RUNS,
) -> None:
    """Run the SyftBox benchmark"""

    # Lazy import to improve cli startup speed
    from syftbox.client.benchmark.report import ConsoleReport, JSONReport
    from syftbox.client.benchmark.runner import SyftBenchmarkRunner
    from syftbox.lib.client_config import SyftClientConfig

    try:
        print("Running benchmarks")
        config = SyftClientConfig.load(config_path)
        benchmark_reporter = JSONReport(json) if json else ConsoleReport()
        benchmark_runner = SyftBenchmarkRunner(config, benchmark_reporter)
        benchmark_runner.run(num_runs)
    except Exception as e:
        rprint(f"[red]Error[/red]: {e}")
        raise e


def main() -> None:
    app()


if __name__ == "__main__":
    main()
