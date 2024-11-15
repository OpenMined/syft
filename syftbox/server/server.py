import contextlib
import json
import os
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from fastapi import Depends, FastAPI, Header, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from jinja2 import Template
from loguru import logger
from typing_extensions import Any, Union

from syftbox.__version__ import __version__
from syftbox.lib.keycloak import CLIENT_ID, KEYCLOAK_REALM, KEYCLOAK_URL
from syftbox.lib.lib import (
    Jsonable,
    get_datasites,
)
from syftbox.server.analytics import log_analytics_event
from syftbox.server.logger import setup_logger
from syftbox.server.middleware import LoguruMiddleware
from syftbox.server.settings import ServerSettings, get_server_settings

from .sync import db, hash
from .sync.router import router as sync_router
from .users.router import create_keycloak_admin_token, user_router

current_dir = Path(__file__).parent


def load_dict(cls, filepath: str) -> Optional[dict[str, Any]]:
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

    def __repr__(self) -> str:
        string = ""
        for email, user in self.users.items():
            string += f"{email}: {user}"
        return string


def create_folders(folders: list[str]) -> None:
    for folder in folders:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)


def init_db(settings: ServerSettings) -> None:
    # might take very long as snapshot folder grows
    logger.info(f"> Collecting Files from {settings.snapshot_folder.absolute()}")
    files = hash.collect_files(settings.snapshot_folder.absolute())
    logger.info("> Hashing files")
    metadata = hash.hash_files(files, settings.snapshot_folder)
    logger.info(f"> Updating file hashes at {settings.file_db_path.absolute()}")
    con = db.get_db(settings.file_db_path.absolute())
    cur = con.cursor()
    for m in metadata:
        db.save_file_metadata(cur, m)

    cur.close()
    con.commit()
    con.close()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI, settings: Optional[ServerSettings] = None):
    # Startup
    if settings is None:
        settings = ServerSettings()

    setup_logger(logs_folder=settings.logs_folder)

    logger.info(f"> Starting SyftBox Server {__version__}. Python {platform.python_version()}")
    logger.info(settings)

    logger.info("> Creating Folders")
    create_folders(settings.folders)
    init_db(settings)

    yield {
        "server_settings": settings,
    }

    logger.info("> Shutting down server")


app = FastAPI(lifespan=lifespan)
app.include_router(sync_router)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
app.add_middleware(LoguruMiddleware)

app.include_router(user_router)

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


def get_file_list(directory: Union[str, Path] = ".") -> list[dict[str, Any]]:
    # TODO rewrite with pathlib
    directory = str(directory)

    file_list = []
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        is_dir = os.path.isdir(item_path)
        size = os.path.getsize(item_path) if not is_dir else "-"
        mod_time = datetime.fromtimestamp(os.path.getmtime(item_path)).strftime("%Y-%m-%d %H:%M:%S")

        file_list.append({"name": item, "is_dir": is_dir, "size": size, "mod_time": mod_time})

    return sorted(file_list, key=lambda x: (not x["is_dir"], x["name"].lower()))


@app.get("/datasites", response_class=HTMLResponse)
async def list_datasites(request: Request, server_settings: ServerSettings = Depends(get_server_settings)):
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
            elif slug_path.endswith(".json") or slug_path.endswith(".jsonl"):
                return FileResponse(slug_path, media_type="application/json")
            elif slug_path.endswith(".yaml") or slug_path.endswith(".yml"):
                return FileResponse(slug_path, media_type="application/x-yaml")
            elif slug_path.endswith(".log") or slug_path.endswith(".txt"):
                return FileResponse(slug_path, media_type="text/plain")
            elif slug_path.endswith(".py"):
                return FileResponse(slug_path, media_type="text/plain")
            else:
                return FileResponse(slug_path, media_type="application/octet-stream")

        # show directory
        if not path.endswith("/") and os.path.exists(path + "/") and os.path.isdir(path + "/"):
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
            # return 404
            message_404 = f"No file or directory found at /datasites/{datasite_part}{slug}"
            return HTMLResponse(content=message_404, status_code=404)

    return f"No Datasite {datasite_part} exists"


@app.post("/invite")
async def invite(email: str, firstName: str, lastName: str):
    admin_token = create_keycloak_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

    payload = {
        "firstName": firstName,
        "lastName": lastName,
        "email": email,
        "enabled": "true",
        "username": email,
        "requiredActions": ["UPDATE_PASSWORD", "UPDATE_PROFILE"],
    }
    resp = requests.post(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users", headers=headers, data=json.dumps(payload)
    )
    if resp.status_code == 201:
        resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users", headers=headers)
        content = resp.json()
        for user in content:
            if user["username"] == email:
                user_id = user["id"]
                actions = ["UPDATE_PASSWORD", "UPDATE_PROFILE"]

                resp = requests.put(
                    f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/execute-actions-email?client_id={CLIENT_ID}",
                    headers=headers,
                    data=json.dumps(actions),
                )
                return resp.status_code, resp.text

        return f"error user {email} not found after creation"
    else:
        return resp.status_code, resp.text


@app.post("/log_event")
async def log_event(request: Request, email: Optional[str] = Header(default=None)):
    data = await request.json()
    log_analytics_event("/log_event", email, **data)
    return JSONResponse({"status": "success"}, status_code=200)


@app.get("/install.sh")
async def install():
    install_script = current_dir / "templates" / "install.sh"
    return FileResponse(install_script, media_type="text/plain")


@app.get("/info")
async def info():
    return {
        "version": __version__,
    }
