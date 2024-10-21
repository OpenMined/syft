import argparse
import contextlib
import json
import os
import platform
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from jinja2 import Template
from loguru import logger
from typing_extensions import Any, Optional

from syftbox.__version__ import __version__
from syftbox.lib import (
    Jsonable,
    PermissionTree,
    bintostr,
    filter_read_state,
    get_datasites,
    hash_dir,
    strtobin,
)
from syftbox.server.models import (
    DirStateRequest,
    DirStateResponse,
    ListDatasitesResponse,
    ReadRequest,
    ReadResponse,
    WriteRequest,
    WriteResponse,
)
from syftbox.server.settings import ServerSettings, get_server_settings

current_dir = Path(__file__).parent


def load_list(cls, filepath: str) -> list[Any]:
    try:
        with open(filepath) as f:
            data = f.read()
            d = json.loads(data)
            ds = []
            for di in d:
                ds.append(cls(**di))
            return ds
    except Exception as e:
        logger.info(f"Unable to load list file: {filepath}. {e}")
    return None


def save_list(obj: Any, filepath: str) -> None:
    dicts = []
    for d in obj:
        dicts.append(d.to_dict())
    with open(filepath, "w") as f:
        f.write(json.dumps(dicts))


def load_dict(cls, filepath: str) -> list[Any]:
    try:
        with open(filepath) as f:
            data = f.read()
            d = json.loads(data)
            dicts = {}
            for key, value in d.items():
                dicts[key] = cls(**value)
            return dicts
    except Exception as e:
        logger.info(f"Unable to load dict file: {filepath}. {e}")
    return None


def save_dict(obj: Any, filepath: str) -> None:
    dicts = {}
    for key, value in obj.items():
        dicts[key] = value.to_dict()

    with open(filepath, "w") as f:
        f.write(json.dumps(dicts))


@dataclass
class User(Jsonable):
    email: str
    token: int  # TODO


class Users:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.users = {}
        self.load()

    def load(self):
        if os.path.exists(str(self.path)):
            users = load_dict(User, str(self.path))
        else:
            users = None
        if users:
            self.users = users

    def save(self):
        save_dict(self.users, str(self.path))

    def get_user(self, email: str) -> Optional[User]:
        if email not in self.users:
            return None
        return self.users[email]

    def create_user(self, email: str) -> int:
        if email in self.users:
            # for now just return the token
            return self.users[email].token
            # raise Exception(f"User already registered: {email}")
        token = random.randint(0, sys.maxsize)
        user = User(email=email, token=token)
        self.users[email] = user
        self.save()
        return token

    def __repr__(self) -> str:
        string = ""
        for email, user in self.users.items():
            string += f"{email}: {user}"
        return string


def get_users(request: Request) -> Users:
    return request.state.users


def create_folders(folders: list[str]) -> None:
    for folder in folders:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI, settings: ServerSettings | None = None):
    # Startup
    logger.info(
        f"> Starting SyftBox Server {__version__}. Python {platform.python_version()}"
    )
    if settings is None:
        settings = ServerSettings()
    logger.info(settings)

    logger.info("> Creating Folders")

    create_folders(settings.folders)

    users = Users(path=settings.user_file_path)
    logger.info("> Loading Users")
    logger.info(users)

    yield {
        "server_settings": settings,
        "users": users,
    }

    logger.info("> Shutting down server")


app = FastAPI(lifespan=lifespan)
# Define the ASCII art
ascii_art = rf"""
 ____         __ _   ____
/ ___| _   _ / _| |_| __ )  _____  __
\___ \| | | | |_| __|  _ \ / _ \ \/ /
 ___) | |_| |  _| |_| |_) | (_) >  <
|____/ \__, |_|  \__|____/ \___/_/\_\
       |___/        {__version__:>17}


# Install Syftbox (MacOS and Linux)
curl -LsSf https://syftbox.openmined.org/install.sh | sh

# Run the client
syftbox client
"""


@app.get("/", response_class=PlainTextResponse)
async def get_ascii_art(request: Request):
    req_host = request.headers.get("host", "")
    if "syftboxstage" in req_host:
        return ascii_art.replace("syftbox.openmined.org", "syftboxstage.openmined.org")
    return ascii_art


@app.get("/wheel/{path:path}", response_class=HTMLResponse)
async def get_wheel(path: str):
    if path == "":  # Check if path is empty (meaning "/datasites/")
        return RedirectResponse(url="/")

    filename = path.split("/")[0]
    if filename.endswith(".whl"):
        wheel_path = os.path.expanduser("~/syftbox-0.1.0-py3-none-any.whl")
        return FileResponse(wheel_path, media_type="application/octet-stream")
    return filename


def get_file_list(directory: str | Path = ".") -> list[dict[str, Any]]:
    # TODO rewrite with pathlib
    directory = str(directory)

    file_list = []
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        is_dir = os.path.isdir(item_path)
        size = os.path.getsize(item_path) if not is_dir else "-"
        mod_time = datetime.fromtimestamp(os.path.getmtime(item_path)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        file_list.append(
            {"name": item, "is_dir": is_dir, "size": size, "mod_time": mod_time}
        )

    return sorted(file_list, key=lambda x: (not x["is_dir"], x["name"].lower()))


@app.get("/datasites", response_class=HTMLResponse)
async def list_datasites(
    request: Request, server_settings: ServerSettings = Depends(get_server_settings)
):
    files = get_file_list(server_settings.snapshot_folder)
    template_path = current_dir / "templates" / "datasites.html"
    html = ""
    with open(template_path) as f:
        html = f.read()
    template = Template(html)

    html_content = template.render(
        {
            "request": request,
            "files": files,
            "current_path": "/",
        }
    )
    return html_content


@app.get("/datasites/{path:path}", response_class=HTMLResponse)
async def browse_datasite(
    request: Request,
    path: str,
    server_settings: ServerSettings = Depends(get_server_settings),
):
    if path == "":  # Check if path is empty (meaning "/datasites/")
        return RedirectResponse(url="/datasites")

    snapshot_folder = str(server_settings.snapshot_folder)
    datasite_part = path.split("/")[0]
    datasites = get_datasites(snapshot_folder)
    if datasite_part in datasites:
        slug = path[len(datasite_part) :]
        if slug == "":
            slug = "/"
        datasite_path = os.path.join(snapshot_folder, datasite_part)
        datasite_public = datasite_path + "/public"
        if not os.path.exists(datasite_public):
            return "No public datasite"

        slug_path = os.path.abspath(datasite_public + slug)
        if os.path.exists(slug_path) and os.path.isfile(slug_path):
            if slug_path.endswith(".html") or slug_path.endswith(".htm"):
                return FileResponse(slug_path)
            elif slug_path.endswith(".md"):
                with open(slug_path, "r") as file:
                    content = file.read()
                return PlainTextResponse(content)
            else:
                return FileResponse(slug_path, media_type="application/octet-stream")

        # show directory
        if not path.endswith("/"):
            return RedirectResponse(url=f"{path}/")

        index_file = os.path.abspath(slug_path + "/" + "index.html")
        if os.path.exists(index_file):
            with open(index_file, "r") as file:
                html_content = file.read()
            return HTMLResponse(content=html_content, status_code=200)

        if os.path.isdir(slug_path):
            files = get_file_list(slug_path)
            template_path = current_dir / "templates" / "folder.html"
            html = ""
            with open(template_path) as f:
                html = f.read()
            template = Template(html)
            html_content = template.render(
                {
                    "datasite": datasite_part,
                    "request": request,
                    "files": files,
                    "current_path": path,
                }
            )
            return html_content
        else:
            return f"Bad Slug {slug}"

    return f"No Datasite {datasite_part} exists"


@app.post("/register")
async def register(request: Request, users: Users = Depends(get_users)):
    data = await request.json()
    email = data["email"]
    token = users.create_user(email)
    logger.info(f"> {email} registering: {token}")
    return JSONResponse({"status": "success", "token": token}, status_code=200)


@app.post("/write", response_model=WriteResponse)
async def write(
    request: WriteRequest,
    server_settings: ServerSettings = Depends(get_server_settings),
) -> WriteResponse:
    try:
        email = request.email
        change = request.change
        reason = "ok"

        change.sync_folder = os.path.abspath(str(server_settings.snapshot_folder))
        result = True
        accepted = True
        if change.newer():
            if change.kind_write:
                if request.is_directory:
                    # Handle empty directory
                    os.makedirs(change.full_path, exist_ok=True)
                    result = True
                else:
                    bin_data = strtobin(request.data)
                    result = change.write(bin_data)
            elif change.kind_delete:
                if change.hash_equal_or_none():
                    result = change.delete()
                else:
                    reason = f"> 🔥 {change.kind} hash doesnt match so ignore {change}"
                    logger.info(reason)
                    accepted = False
            else:
                raise Exception(f"Unknown type of change kind. {change.kind}")
        else:
            reason = f"> 🔥 {change.kind} is older so ignore {change}"
            logger.info(reason)
            accepted = False

        if result:
            logger.info(f"> {email} {change.kind}: {change.internal_path}")
            return WriteResponse(
                status="success",
                change=change,
                accepted=accepted,
                reason=reason,
            )
        return WriteResponse(
            status="error",
            change=change,
            accepted=accepted,
            reason=reason,
        ), 400
    except Exception as e:
        logger.info("Exception writing", e)
        raise HTTPException(
            status_code=400,
            detail=f"Exception writing {e}",
        )


@app.post("/read", response_model=ReadResponse)
async def read(
    request: ReadRequest, server_settings: ServerSettings = Depends(get_server_settings)
) -> ReadResponse:
    email = request.email
    change = request.change
    change.sync_folder = os.path.abspath(str(server_settings.snapshot_folder))
    logger.info(f"> {email} {change.kind}: {change.internal_path}")
    # TODO: handle permissions, create and delete
    data = None
    if change.kind_write and not change.is_directory():
        data = bintostr(change.read())
    return ReadResponse(
        status="success",
        change=change.model_dump(mode="json"),
        data=data,
        is_directory=change.is_directory(),
    )


@app.post("/dir_state", response_model=DirStateResponse)
async def dir_state(
    request: DirStateRequest,
    server_settings: ServerSettings = Depends(get_server_settings),
) -> DirStateResponse:
    try:
        email = request.email
        sub_path = request.sub_path
        snapshot_folder = str(server_settings.snapshot_folder)
        full_path = os.path.join(snapshot_folder, sub_path)
        remote_dir_state = hash_dir(snapshot_folder, sub_path)

        # get the top level perm file
        try:
            perm_tree = PermissionTree.from_path(
                full_path, raise_on_corrupted_files=True
            )
        except Exception as e:
            print(f"Failed to parse permission tree: {full_path}")
            raise e

        # filter the read state for this user by the perm tree
        read_state = filter_read_state(email, remote_dir_state, perm_tree)
        remote_dir_state.tree = read_state

        if remote_dir_state:
            return DirStateResponse(
                sub_path=sub_path,
                dir_state=remote_dir_state,
                status="success",
            )
        raise HTTPException(status_code=400, detail={"status": "error"})
    except Exception as e:
        logger.exception("Failed to run /dir_state", e)


@app.get("/list_datasites", response_model=ListDatasitesResponse)
async def datasites(
    server_settings: ServerSettings = Depends(get_server_settings),
) -> ListDatasitesResponse:
    datasites = get_datasites(server_settings.snapshot_folder)
    if isinstance(datasites, list):
        return ListDatasitesResponse(
            datasites=datasites,
            status="success",
        )
    raise HTTPException(status_code=400, detail={"status": "error"})


@app.get("/install.sh")
async def install():
    install_script = current_dir / "templates" / "install.sh"
    return FileResponse(install_script, media_type="text/plain")


@app.get("/info")
async def info():
    return {
        "version": __version__,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run FastAPI server")
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="Port to run the server on (default: 5001)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run the server in debug mode with hot reloading",
    )
    parser.add_argument(
        "--ssl-keyfile",
        type=str,
        help="Path to SSL key file for HTTPS",
    )
    parser.add_argument(
        "--ssl-keyfile-password",
        type=str,
        help="SSL key file password for HTTPS",
    )
    parser.add_argument(
        "--ssl-certfile",
        type=str,
        help="Path to SSL certificate file for HTTPS",
    )

    args = parser.parse_args()
    return args


def main() -> None:
    args = parse_args()
    uvicorn_config = {
        "app": "syftbox.server.server:app" if args.debug else app,
        "host": "0.0.0.0",
        "port": args.port,
        "log_level": "debug" if args.debug else "info",
        "reload": args.debug,
    }

    uvicorn_config["ssl_keyfile"] = args.ssl_keyfile if args.ssl_keyfile else None
    uvicorn_config["ssl_certfile"] = args.ssl_certfile if args.ssl_certfile else None
    uvicorn_config["ssl_keyfile_password"] = (
        args.ssl_keyfile_password if args.ssl_keyfile_password else None
    )

    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()
