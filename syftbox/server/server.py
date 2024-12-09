import contextlib
import os
import platform
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Request
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
from typing_extensions import Any, Optional, Union

from syftbox import __version__
from syftbox.lib.constants import PERM_FILE
from syftbox.lib.hash import collect_files, hash_files
from syftbox.lib.lib import (
    get_datasites,
)
from syftbox.lib.permissions import SyftPermission, migrate_permissions
from syftbox.server.analytics import log_analytics_event
from syftbox.server.db import db
from syftbox.server.db.schema import get_db
from syftbox.server.logger import setup_logger
from syftbox.server.middleware import LoguruMiddleware
from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.users.auth import get_current_user

from .api.v1.sync_router import router as sync_router
from .emails.router import router as emails_router
from .users.router import router as users_router

current_dir = Path(__file__).parent


def create_folders(folders: list[str]) -> None:
    for folder in folders:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)


def init_db(settings: ServerSettings) -> None:
    # remove this after the upcoming release
    if __version__ in ["0.2.11", "0.2.12"]:
        # Delete existing DB to avoid conflicts
        db_path = settings.file_db_path.absolute()
        if db_path.exists():
            db_path.unlink()
    migrate_permissions(settings.snapshot_folder)

    # might take very long as snapshot folder grows
    logger.info(f"> Collecting Files from {settings.snapshot_folder.absolute()}")
    files = collect_files(settings.snapshot_folder.absolute())
    logger.info("> Hashing files")
    metadata = hash_files(files, settings.snapshot_folder)
    logger.info(f"> Updating file hashes at {settings.file_db_path.absolute()}")
    con = get_db(settings.file_db_path.absolute())
    cur = con.cursor()
    for m in metadata:
        db.save_file_metadata(cur, m)

    # remove files that are not in the snapshot folder
    all_metadata = db.get_all_metadata(cur)
    for m in all_metadata:
        abs_path = settings.snapshot_folder / m.path
        if not abs_path.exists():
            logger.info(f"{m.path} not found in {settings.snapshot_folder}, deleting from db")
            db.delete_file_metadata(cur, m.path.as_posix())

    # fill the permission tables
    for file in settings.snapshot_folder.rglob(PERM_FILE):
        content = file.read_text()
        rule_dicts = yaml.safe_load(content)
        perm_file = SyftPermission.from_rule_dicts(
            permfile_file_path=file.relative_to(settings.snapshot_folder), rule_dicts=rule_dicts
        )
        db.set_rules_for_permfile(con, perm_file)
        db.link_existing_rules_to_file(con, file.relative_to(settings.snapshot_folder))

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

    logger.info("> Loading Users")

    init_db(settings)

    yield {
        "server_settings": settings,
    }

    logger.info("> Shutting down server")


app = FastAPI(lifespan=lifespan)
app.include_router(emails_router)
app.include_router(sync_router)
app.include_router(users_router)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
app.add_middleware(LoguruMiddleware)

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


@app.post("/register")
async def register(
    request: Request,
    server_settings: ServerSettings = Depends(get_server_settings),
):
    data = await request.json()
    email = data["email"]

    # create datasite snapshot folder
    datasite_folder = Path(server_settings.snapshot_folder) / email
    os.makedirs(datasite_folder, exist_ok=True)

    logger.info(f"> {email} registering, snapshot folder: {datasite_folder}")
    log_analytics_event("/register", email)

    return JSONResponse({"status": "success", "token": "0"}, status_code=200)


@app.post("/log_event")
async def log_event(
    request: Request,
    email: str = Depends(get_current_user),
):
    data = await request.json()
    log_analytics_event("/log_event", email, **data)
    return JSONResponse({"status": "success"}, status_code=200)


@app.get("/install.sh")
async def install():
    install_script = current_dir / "templates" / "install.sh"
    return FileResponse(install_script, media_type="text/plain")


@app.get("/icon.png")
async def icon():
    icon_path = current_dir / "assets" / "icon.png"
    return FileResponse(icon_path, media_type="image/png")


@app.get("/info")
async def info():
    return {
        "version": __version__,
    }
