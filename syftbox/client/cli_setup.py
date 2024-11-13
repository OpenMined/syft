"""
SyftBox CLI - Setup scripts
"""

from pathlib import Path

from rich import print as rprint
from rich.prompt import Confirm, Prompt

from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.constants import DEFAULT_DATA_DIR
from syftbox.lib.exceptions import ClientConfigException
from syftbox.lib.validators import DIR_NOT_EMPTY, is_valid_dir, is_valid_email
from syftbox.lib.keycloak import get_token, get_ttl_hash

__all__ = ["setup_config_interactive"]


def setup_config_interactive(
    config_path: Path, 
    email: str, 
    data_dir: Path, 
    server: str, 
    port: int, 
    register: bool,
    reset_password: bool,
) -> SyftClientConfig:
    """Setup the client configuration interactively. Called from CLI"""

    config_path = config_path.expanduser().resolve()
    conf: SyftClientConfig = None
    if data_dir:
        data_dir = data_dir.expanduser().resolve()

    # try to load the existing config
    try:
        conf = SyftClientConfig.load(config_path)
    except ClientConfigException:
        pass

    if not conf:
        # first time setup
        if not data_dir or data_dir == DEFAULT_DATA_DIR:
            data_dir = prompt_data_dir()

        if not email:
            email = prompt_email()
            
        password = register_password() if register else login_password()
        
        token = get_token(email, password, ttl=get_ttl_hash())

        # create a new config with the input params
        conf = SyftClientConfig(
            path=config_path,
            sync_folder=data_dir,
            email=email,
            server_url=server,
            port=port,
            token=token,
            password=password,
        )
    else:
        if server and server != conf.server_url:
            conf.set_server_url(server)
        if port != conf.client_url.port:
            conf.set_port(port)
            
    if reset_password:
        if register:
            rprint("You cannot register and reset password at the same time!")
            exit()
        else:
            new_password = register_password()
            resp = reset_password(conf.user_id, new_password, conf.token)
            if resp.status_code == 204:
                rprint("[bold]Password reset succesful![/bold]")
            else:
                rprint("[bold red]An error occured![/bold red] '{resp.text}'")
                exit()

    # DO NOT SAVE THE CONFIG HERE.
    # We don't know if the client will accept the config yet
    return conf


def prompt_data_dir(default_dir: Path = DEFAULT_DATA_DIR) -> Path:
    prompt_dir = "[bold]Where do you want SyftBox to store data?[/bold] [grey70]Press Enter for default[/grey70]"
    prompt_overwrite = "[bold yellow]Directory '{sync_folder}' is not empty![/bold yellow] Do you want to overwrite it?"

    while True:
        sync_folder = Prompt.ask(prompt_dir, default=str(default_dir))
        valid, reason = is_valid_dir(sync_folder)
        if reason == DIR_NOT_EMPTY:
            overwrite = Confirm.ask(prompt_overwrite.format(sync_folder=sync_folder))
            if not overwrite:
                continue
            valid = True

        if not valid:
            rprint(f"[bold red]{reason}[/bold red] '{sync_folder}'")
            continue

        path = Path(sync_folder).expanduser().resolve()
        rprint(f"Selected directory [bold]'{path}'[/bold]")
        return path


def prompt_email() -> str:
    while True:
        email = Prompt.ask("[bold]Enter your email address[/bold]")
        if not is_valid_email(email):
            rprint(f"[bold red]Invalid email[/bold red]: '{email}'")
            continue
        return email
    
def register_password() -> str:
    while True:
        password = Prompt.ask("[bold]Enter your password[/bold]")
        verify_password = Prompt.ask("[bold]Verify your password[/bold]")
        if password == verify_password:
            break
        rprint(f"[bold red]Passwords don't match! Please try again.[/bold red]")
    return password

def login_password() -> str:
    return Prompt.ask("[bold]Password:[/bold]")