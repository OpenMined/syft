from pathlib import Path
from typing import Annotated, Optional

from typer import Context, Option, Typer

app = Typer(
    name="SyftBox Server",
    pretty_exceptions_enable=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# Define options separately to keep the function signature clean
# fmt: off
SERVER_PANEL = "Server Options"
SSL_PANEL = "SSL Options"

PORT_OPTS = Option(
    "-p", "--port",
    rich_help_panel=SERVER_PANEL,
    help="Local port for the SyftBox client",
)
WORKERS_OPTS = Option(
    "-w", "--workers",
    rich_help_panel=SERVER_PANEL,
    help="Number of worker processes",
)
VERBOSE_OPTS = Option(
    "-v", "--verbose",
    is_flag=True,
    rich_help_panel=SERVER_PANEL,
    help="Enable verbose mode",
)
RELOAD_OPTS = Option(
    "--reload", "--debug",
    rich_help_panel=SERVER_PANEL,
    help="Enable debug mode",
)
EMAIL_OPTS = Option(
    "-e", "--email",
    rich_help_panel=SERVER_PANEL,
    help="Email to ban/unban",
)
SSL_KEY_OPTS = Option(
    "--key", "--ssl-keyfile",
    exists=True, file_okay=True, readable=True,
    rich_help_panel=SSL_PANEL,
    help="Path to SSL key file",
)
SSL_CERT_OPTS = Option(
    "--cert", "--ssl-certfile",
    exists=True, file_okay=True, readable=True,
    rich_help_panel=SSL_PANEL,
    help="Path to SSL certificate file",
)
# fmt: on


@app.callback(invoke_without_command=True)
def server(
    ctx: Context,
    port: Annotated[int, PORT_OPTS] = 5001,
    workers: Annotated[int, WORKERS_OPTS] = 1,
    verbose: Annotated[bool, VERBOSE_OPTS] = False,
    ssl_key: Annotated[Optional[Path], SSL_KEY_OPTS] = None,
    ssl_cert: Annotated[Optional[Path], SSL_CERT_OPTS] = None,
):
    """Run the SyftBox server"""

    if ctx.invoked_subcommand is not None:
        return

    # lazy import to improve CLI startup performance
    import uvicorn

    from syftbox.server.server import app as fastapi_app

    uvicorn.run(
        app=fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="debug" if verbose else "info",
        workers=workers,
        ssl_keyfile=ssl_key,
        ssl_certfile=ssl_cert,
    )


def main():
    app()


if __name__ == "__main__":
    main()
