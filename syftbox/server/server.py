import argparse
import contextlib
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from jinja2 import Template
from typing_extensions import Any

from syftbox.lib import (
    FileChange,
    FileChangeKind,
    Jsonable,
    PermissionTree,
    bintostr,
    filter_read_state,
    get_datasites,
    hash_dir,
    strtobin,
)

from .users.router import user_router
from .users.user import UserManager

current_dir = Path(__file__).parent


DATA_FOLDER = "data"
SNAPSHOT_FOLDER = f"{DATA_FOLDER}/snapshot"
USER_FILE_PATH = f"{DATA_FOLDER}/users.json"

FOLDERS = [DATA_FOLDER, SNAPSHOT_FOLDER]


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
        print(f"Unable to load dict file: {filepath}. {e}")
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
    def __init__(self) -> None:
        self.users = {}
        self.load()

    def load(self):
        if os.path.exists(USER_FILE_PATH):
            users = load_dict(User, USER_FILE_PATH)
        else:
            users = None
        if users:
            self.users = users

    def save(self):
        save_dict(self.users, USER_FILE_PATH)

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

    # def key_for_email(self, email: str) -> int | None:
    #     user = self.get_user(email)
    #     if user:
    #         return user.public_key
    #     return None


USERS = Users()


def create_folders(folders: list[str]) -> None:
    for folder in folders:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("> Starting Server")
    print("> Creating Folders")
    create_folders(FOLDERS)
    print("> Loading Users")
    print(USERS)

    state = {
        "user_manager": UserManager(),
    }

    yield state

    print("> Shutting down server")


app = FastAPI(lifespan=lifespan)

app.include_router(user_router)

# Define the ASCII art
ascii_art = r"""
 ____         __ _   ____
/ ___| _   _ / _| |_| __ )  _____  __
\___ \| | | | |_| __|  _ \ / _ \ \/ /
 ___) | |_| |  _| |_| |_) | (_) >  <
|____/ \__, |_|  \__|____/ \___/_/\_\
       |___/


# MacOS and Linux
Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# create a virtualenv somewhere
uv venv .venv

# install the wheel
uv pip install http://20.168.10.234:8080/wheel/syftbox-0.1.0-py3-none-any.whl --reinstall

# run the client
uv run syftbox client
"""


@app.get("/", response_class=PlainTextResponse)
async def get_ascii_art():
    return ascii_art


@app.get("/wheel/{path:path}", response_class=HTMLResponse)
async def get_wheel(request: Request, path: str):
    if path == "":  # Check if path is empty (meaning "/datasites/")
        return RedirectResponse(url="/")

    filename = path.split("/")[0]
    if filename.endswith(".whl"):
        wheel_path = os.path.expanduser("~/syftbox-0.1.0-py3-none-any.whl")
        return FileResponse(wheel_path, media_type="application/octet-stream")
    return filename


def get_file_list(directory="."):
    file_list = []
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        is_dir = os.path.isdir(item_path)
        size = os.path.getsize(item_path) if not is_dir else "-"
        mod_time = datetime.fromtimestamp(os.path.getmtime(item_path)).strftime("%Y-%m-%d %H:%M:%S")

        file_list.append({"name": item, "is_dir": is_dir, "size": size, "mod_time": mod_time})

    return sorted(file_list, key=lambda x: (not x["is_dir"], x["name"].lower()))


@app.get("/datasites", response_class=HTMLResponse)
async def list_datasites(request: Request):
    datasite_path = os.path.join(SNAPSHOT_FOLDER)
    files = get_file_list(datasite_path)
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
async def browse_datasite(request: Request, path: str):
    if path == "":  # Check if path is empty (meaning "/datasites/")
        return RedirectResponse(url="/datasites")

    datasite_part = path.split("/")[0]
    datasites = get_datasites(SNAPSHOT_FOLDER)
    if datasite_part in datasites:
        slug = path[len(datasite_part) :]
        if slug == "":
            slug = "/"
        datasite_path = os.path.join(SNAPSHOT_FOLDER, datasite_part)
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
async def register(request: Request):
    data = await request.json()
    email = data["email"]
    token = USERS.create_user(email)
    print(f"> {email} registering: {token}")
    return JSONResponse({"status": "success", "token": token}, status_code=200)


@app.post("/write")
async def write(request: Request):
    try:
        data = await request.json()
        email = data["email"]
        change_dict = data["change"]
        change_dict["kind"] = FileChangeKind(change_dict["kind"])
        change = FileChange(**change_dict)

        change.sync_folder = os.path.abspath(SNAPSHOT_FOLDER)
        result = True
        accepted = True
        if change.newer():
            if change.kind_write:
                if data.get("is_directory", False):
                    # Handle empty directory
                    os.makedirs(change.full_path, exist_ok=True)
                    result = True
                else:
                    bin_data = strtobin(data["data"])
                    result = change.write(bin_data)
            elif change.kind_delete:
                if change.hash_equal_or_none():
                    result = change.delete()
                else:
                    print(f"> 🔥 {change.kind} hash doesnt match so ignore {change}")
                    accepted = False
            else:
                raise Exception(f"Unknown type of change kind. {change.kind}")
        else:
            print(f"> 🔥 {change.kind} is older so ignore {change}")
            accepted = False

        if result:
            print(f"> {email} {change.kind}: {change.internal_path}")
            json_payload = {
                "status": "success",
                "change": change.to_dict(),
                "accepted": accepted,
            }
            return JSONResponse(
                json_payload,
                status_code=200,
            )
        return JSONResponse(
            {"status": "error", "change": change.to_dict()},
            status_code=400,
        )
    except Exception as e:
        print("Exception writing", e)
        return JSONResponse(
            {"status": "error", "error": str(e)},
            status_code=400,
        )


@app.post("/read")
async def read(request: Request):
    data = await request.json()
    email = data["email"]
    change_dict = data["change"]
    change_dict["kind"] = FileChangeKind(change_dict["kind"])
    change = FileChange(**change_dict)
    change.sync_folder = os.path.abspath(SNAPSHOT_FOLDER)

    json_dict = {"change": change.to_dict()}

    if change.kind_write:
        if os.path.isdir(change.full_path):
            # Handle directory
            json_dict["is_directory"] = True
        else:
            # Handle file
            bin_data = change.read()
            json_dict["data"] = bintostr(bin_data)
    elif change.kind_delete:
        # Handle delete operation if needed
        pass
    else:
        raise Exception(f"Unknown type of change kind. {change.kind}")

    print(f"> {email} {change.kind}: {change.internal_path}")
    return JSONResponse({"status": "success"} | json_dict, status_code=200)


@app.post("/dir_state")
async def dir_state(request: Request):
    try:
        data = await request.json()
        email = data["email"]
        sub_path = data["sub_path"]
        full_path = os.path.join(SNAPSHOT_FOLDER, sub_path)
        remote_dir_state = hash_dir(SNAPSHOT_FOLDER, sub_path)

        # get the top level perm file
        perm_tree = PermissionTree.from_path(full_path)

        # filter the read state for this user by the perm tree
        read_state = filter_read_state(email, remote_dir_state, perm_tree)
        remote_dir_state.tree = read_state

        response_json = {"sub_path": sub_path, "dir_state": remote_dir_state.to_dict()}
        if remote_dir_state:
            return JSONResponse({"status": "success"} | response_json, status_code=200)
        return JSONResponse({"status": "error"}, status_code=400)
    except Exception as e:
        print("Failed to run /dir_state", e)


@app.get("/list_datasites")
async def datasites(request: Request):
    datasites = get_datasites(SNAPSHOT_FOLDER)
    response_json = {"datasites": datasites}
    if datasites:
        return JSONResponse({"status": "success"} | response_json, status_code=200)
    return JSONResponse({"status": "error"}, status_code=400)


def main() -> None:
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

    args = parser.parse_args()

    uvicorn.run(
        "syftbox.server.server:app" if args.debug else app,  # Use import string in debug mode
        host="0.0.0.0",
        port=args.port,
        log_level="debug" if args.debug else "info",
        reload=args.debug,  # Enable hot reloading only in debug mode
    )


if __name__ == "__main__":
    main()
