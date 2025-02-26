from pathlib import Path
from typing import Optional

import httpx

from syftbox.client.auth import authenticate_user
from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.exceptions import ClientConfigException
from syftbox.lib.http import HEADER_SYFTBOX_USER, SYFTBOX_HEADERS


def setup_config_automated(
    config_path: Path,
    email: str,
    data_dir: Path,
    server: str,
    port: int,
    transport: Optional[httpx.Transport] = None,
) -> SyftClientConfig:
    """
    Setup the client configuration automatically. Called by tests.

    NOTE if transport is provided, it will be used for the login client.
    This is useful for testing the client with a mocked transport.
    (for example: fastAPI test client)
    """
    config_path = config_path.expanduser().resolve()
    data_dir = data_dir.expanduser().resolve()

    try:
        conf = SyftClientConfig.load(config_path)
    except ClientConfigException:
        conf = None

    if not conf:
        conf = SyftClientConfig(
            path=config_path,
            sync_folder=data_dir,
            email=email,
            server_url=server,
            port=port,
        )
    else:
        if server and server != conf.server_url:
            conf.set_server_url(server)
        if port != conf.client_url.port:
            conf.set_port(port)

    client_transport = transport or httpx.HTTPTransport(retries=10)
    login_client = httpx.Client(
        base_url=str(conf.server_url),
        headers={
            **SYFTBOX_HEADERS,
            HEADER_SYFTBOX_USER: conf.email,
        },
        transport=client_transport,
    )
    conf.access_token = authenticate_user(conf, login_client)
    return conf
