import argparse
import atexit
import importlib
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import uvicorn
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from syftbox.lib import SharedState
from syftbox.lib.client_config import ClientConfig
from syftbox.lib.util import validate_email

current_dir = Path(__file__).parent
# Initialize FastAPI app and scheduler

templates = Jinja2Templates(directory="templates")


PLUGINS_DIR = current_dir / "plugins"
sys.path.insert(0, os.path.dirname(PLUGINS_DIR))

DEFAULT_SYNC_FOLDER = os.path.expanduser("~/Desktop/SyftBox")
DEFAULT_PORT = 8082
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.syftbox/client_config.json")
ASSETS_FOLDER = current_dir.parent / "assets"
ICON_FOLDER = ASSETS_FOLDER / "icon"

WATCHDOG_IGNORE = ["apps"]


@dataclass
class Plugin:
    name: str
    module: types.ModuleType
    schedule: int
    description: str


# if you knew the pain of this function
def find_icon_file(src_folder: str) -> Path:
    src_path = Path(src_folder)

    # Function to search for Icon\r file
    def search_icon_file():
        if os.path.exists(src_folder):
            for file_path in src_path.iterdir():
                if "Icon" in file_path.name and "\r" in file_path.name:
                    return file_path
        return None

    # First attempt to find the Icon\r file
    icon_file = search_icon_file()
    if icon_file:
        return icon_file

    # If Icon\r is not found, search for icon.zip and unzip it
    zip_file = ASSETS_FOLDER / "icon.zip"

    if zip_file.exists():
        try:
            # cant use other zip tools as they don't unpack it correctly
            subprocess.run(
                ["ditto", "-xk", str(zip_file), str(src_path.parent)],
                check=True,
            )

            # Try to find the Icon\r file again after extraction
            icon_file = search_icon_file()
            if icon_file:
                return icon_file
        except subprocess.CalledProcessError:
            raise RuntimeError("Failed to unzip icon.zip using macOS CLI tool.")

    # If still not found, raise an error
    raise FileNotFoundError(
        "Icon file with a carriage return not found, and icon.zip did not contain it.",
    )


def copy_icon_file(icon_folder: str, dest_folder: str) -> None:
    src_icon_path = find_icon_file(icon_folder)
    if not os.path.isdir(dest_folder):
        raise FileNotFoundError(f"Destination folder '{dest_folder}' does not exist.")

    # shutil wont work with these special icon files
    subprocess.run(["cp", "-p", src_icon_path, dest_folder], check=True)
    subprocess.run(["SetFile", "-a", "C", dest_folder], check=True)


def load_or_create_config(args) -> ClientConfig:
    syft_config_dir = os.path.abspath(os.path.expanduser("~/.syftbox"))
    os.makedirs(syft_config_dir, exist_ok=True)

    client_config = None
    try:
        client_config = ClientConfig.load(args.config_path)
    except Exception:
        pass

    if client_config is None and args.config_path:
        config_path = os.path.abspath(os.path.expanduser(args.config_path))
        client_config = ClientConfig(config_path=config_path)

    if client_config is None:
        # config_path = get_user_input("Path to config file?", DEFAULT_CONFIG_PATH)
        config_path = os.path.abspath(os.path.expanduser(config_path))
        client_config = ClientConfig(config_path=config_path)

    if args.sync_folder:
        sync_folder = os.path.abspath(os.path.expanduser(args.sync_folder))
        client_config.sync_folder = sync_folder

    if client_config.sync_folder is None:
        sync_folder = get_user_input(
            "Where do you want to Sync SyftBox to?",
            DEFAULT_SYNC_FOLDER,
        )
        sync_folder = os.path.abspath(os.path.expanduser(sync_folder))
        client_config.sync_folder = sync_folder

    if args.server:
        client_config.server_url = args.server

    if not os.path.exists(client_config.sync_folder):
        os.makedirs(client_config.sync_folder, exist_ok=True)

    if platform.system() == "Darwin":
        copy_icon_file(ICON_FOLDER, client_config.sync_folder)

    if args.email:
        client_config.email = args.email

    if client_config.email is None:
        email = get_user_input("What is your email address? ")
        if not validate_email(email):
            raise Exception(f"Invalid email: {email}")
        client_config.email = email

    if args.port:
        client_config.port = args.port

    if client_config.port is None:
        port = int(get_user_input("Enter the port to use", DEFAULT_PORT))
        client_config.port = port

    email_token = os.environ.get("EMAIL_TOKEN", None)
    if email_token:
        client_config.email_token = email_token

    client_config.save(args.config_path)
    return client_config


def get_user_input(prompt, default: Optional[str] = None):
    if default:
        prompt = f"{prompt} (default: {default}): "
    user_input = input(prompt).strip()
    return user_input if user_input else default


def process_folder_input(user_input, default_path):
    if not user_input:
        return default_path
    if "/" not in user_input:
        # User only provided a folder name, use it with the default parent path
        parent_path = os.path.dirname(default_path)
        return os.path.join(parent_path, user_input)
    return os.path.expanduser(user_input)


def initialize_shared_state(client_config: ClientConfig) -> SharedState:
    shared_state = SharedState(client_config=client_config)
    return shared_state


def load_plugins(client_config: ClientConfig) -> dict[str, Plugin]:
    loaded_plugins = {}
    if os.path.exists(PLUGINS_DIR) and os.path.isdir(PLUGINS_DIR):
        for item in os.listdir(PLUGINS_DIR):
            if item.endswith(".py") and not item.startswith("__"):
                plugin_name = item[:-3]
                try:
                    module = importlib.import_module(f"plugins.{plugin_name}")
                    schedule = getattr(
                        module,
                        "DEFAULT_SCHEDULE",
                        5000,
                    )  # Default to 5000ms if not specified
                    description = getattr(
                        module,
                        "DESCRIPTION",
                        "No description available.",
                    )
                    plugin = Plugin(
                        name=plugin_name,
                        module=module,
                        schedule=schedule,
                        description=description,
                    )
                    loaded_plugins[plugin_name] = plugin
                except Exception as e:
                    print(e)

    return loaded_plugins


def generate_key_pair() -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return private_pem, public_pem


def is_valid_datasite_name(name):
    return name.isalnum() or all(c.isalnum() or c in ("-", "_") for c in name)


@dataclass
class Plugin:
    name: str
    module: types.ModuleType
    schedule: int
    description: str


# API Models
class PluginRequest(BaseModel):
    plugin_name: str


class SharedStateRequest(BaseModel):
    key: str
    value: str


class DatasiteRequest(BaseModel):
    name: str


# Function to be scheduled
def run_plugin(plugin_name, *args, **kwargs):
    try:
        module = app.loaded_plugins[plugin_name].module
        module.run(app.shared_state, *args, **kwargs)
    except Exception as e:
        traceback.print_exc()
        print("error", e)


def start_plugin(plugin_name: str):
    if plugin_name not in app.loaded_plugins:
        raise HTTPException(
            status_code=400,
            detail=f"Plugin {plugin_name} is not loaded",
        )

    if plugin_name in app.running_plugins:
        raise HTTPException(
            status_code=400,
            detail=f"Plugin {plugin_name} is already running",
        )

    try:
        plugin = app.loaded_plugins[plugin_name]

        existing_job = app.scheduler.get_job(plugin_name)
        if existing_job is None:
            job = app.scheduler.add_job(
                func=run_plugin,
                trigger="interval",
                seconds=plugin.schedule / 1000,
                id=plugin_name,
                args=[plugin_name],
            )
            app.running_plugins[plugin_name] = {
                "job": job,
                "start_time": time.time(),
                "schedule": plugin.schedule,
            }
            return {"message": f"Plugin {plugin_name} started successfully"}
        else:
            print(f"Job {existing_job}, already added")
            return {"message": f"Plugin {plugin_name} already started"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start plugin {plugin_name}: {e!s}",
        )


# Parsing arguments and initializing shared state
def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the web application with plugins.",
    )
    parser.add_argument(
        "--config_path", type=str, default=DEFAULT_CONFIG_PATH, help="config path"
    )
    parser.add_argument("--sync_folder", type=str, help="sync folder path")
    parser.add_argument("--email", type=str, help="email")
    parser.add_argument("--port", type=int, default=8080, help="Port number")
    parser.add_argument(
        "--server",
        type=str,
        default="http://20.168.10.234:8080",
        help="Server",
    )
    return parser.parse_args()


def start_watchdog(app):
    shared_state = app.shared_state
    sync_folder = shared_state.client_config.sync_folder

    stop_event = threading.Event()
    app.stop_event = stop_event

    class AnyFileSystemEventHandler(FileSystemEventHandler):
        def on_any_event(self, event: FileSystemEvent) -> None:
            for ignore in WATCHDOG_IGNORE:
                full_path = shared_state.client_config.sync_folder + "/" + ignore
                if event.src_path.startswith(full_path):
                    return
            run_plugin("sync", event)

    event_handler = AnyFileSystemEventHandler()
    observer = Observer()
    observer.schedule(event_handler, sync_folder, recursive=True)
    observer.start()

    # Run observer in a thread to keep the process alive
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        print("> Watchdog received KeyboardInterrupt")
    finally:
        print("> Stopping Watchdog...")
        observer.stop()
        observer.join()
        print("> Watchdog stopped")


async def lifespan(app: FastAPI):
    # Startup
    print("> Starting Client")
    args = parse_args()
    client_config = load_or_create_config(args)
    app.shared_state = initialize_shared_state(client_config)

    # Clear the lock file on the first run if it exists
    job_file = client_config.config_path.replace(".json", ".sql")
    app.job_file = job_file
    if os.path.exists(job_file):
        os.remove(job_file)
        print(f"> Cleared existing job file: {job_file}")

    # Start the scheduler
    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{job_file}")}
    scheduler = BackgroundScheduler(jobstores=jobstores)
    scheduler.start()
    app.scheduler = scheduler
    atexit.register(stop_scheduler)

    app.running_plugins = {}
    app.loaded_plugins = load_plugins(client_config)

    # Start the watchdog observer in a thread
    if not hasattr(app, "watchdog_thread") or not app.watchdog_thread.is_alive():
        print("> Starting Watchdog Thread")
        watchdog_thread = threading.Thread(
            target=start_watchdog, args=(app,), daemon=True
        )
        watchdog_thread.start()
        app.watchdog_thread = watchdog_thread

    autorun_plugins = ["init", "create_datasite", "sync", "apps"]
    # autorun_plugins = ["init", "create_datasite", "sync", "apps"]
    for plugin in autorun_plugins:
        start_plugin(plugin)

    yield  # This yields control to run the application

    print("> Shutting down...")
    scheduler.shutdown()

    if app.watchdog_thread.is_alive():
        app.stop_event.set()
        app.watchdog_thread.join()


def stop_scheduler():
    # Remove the lock file if it exists
    if os.path.exists(app.job_file):
        os.remove(app.job_file)
        print("> Scheduler stopped and lock file removed.")


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory=current_dir / "static"), name="static")


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.get("/", response_class=HTMLResponse)
async def plugin_manager(request: Request):
    # Pass the request to the template to allow FastAPI to render it
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/client_email")
def get_client_email():
    try:
        email = app.shared_state.client_config.email
        return JSONResponse(content={"email": email})
    except AttributeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error accessing client email: {e!s}",
        )


@app.get("/state")
def get_shared_state():
    return JSONResponse(content=app.shared_state.data)


@app.get("/datasites")
def list_datasites():
    datasites = app.shared_state.get("my_datasites", [])
    # Use jsonable_encoder to encode the datasites object
    return JSONResponse(content={"datasites": jsonable_encoder(datasites)})


# FastAPI Routes
@app.get("/plugins")
def list_plugins():
    plugins = [
        {
            "name": plugin_name,
            "default_schedule": plugin.schedule,
            "is_running": plugin_name in app.running_plugins,
            "description": plugin.description,
        }
        for plugin_name, plugin in app.loaded_plugins.items()
    ]
    return {"plugins": plugins}


@app.post("/launch")
def launch_plugin(request: PluginRequest):
    return start_plugin(request.plugin_name)


@app.get("/running")
def list_running_plugins():
    running = {
        name: {
            "is_running": data["job"].next_run_time is not None,
            "run_time": time.time() - data["start_time"],
            "schedule": data["schedule"],
        }
        for name, data in app.running_plugins.items()
    }
    return {"running_plugins": running}


@app.post("/kill")
def kill_plugin(request: PluginRequest):
    plugin_name = request.plugin_name

    if plugin_name not in app.running_plugins:
        raise HTTPException(
            status_code=400,
            detail=f"Plugin {plugin_name} is not running",
        )

    try:
        app.scheduler.remove_job(plugin_name)
        plugin_module = app.loaded_plugins[plugin_name].module
        if hasattr(plugin_module, "stop"):
            plugin_module.stop()
        del app.running_plugins[plugin_name]
        return {"message": f"Plugin {plugin_name} stopped successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop plugin {plugin_name}: {e!s}",
        )


@app.post("/file_operation")
async def file_operation(
    operation: str = Body(...),
    file_path: str = Body(...),
    content: str = Body(None),
):
    full_path = Path(app.shared_state.client_config.sync_folder) / file_path

    # Ensure the path is within the SyftBox directory
    if not full_path.resolve().is_relative_to(
        Path(app.shared_state.client_config.sync_folder),
    ):
        raise HTTPException(
            status_code=403,
            detail="Access to files outside SyftBox directory is not allowed",
        )

    if operation == "read":
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(full_path)

    if operation in ["write", "append"]:
        if content is None:
            raise HTTPException(
                status_code=400,
                detail="Content is required for write or append operation",
            )

        # Ensure the directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            mode = "w" if operation == "write" else "a"
            with open(full_path, mode) as f:
                f.write(content)
            return JSONResponse(content={"message": f"File {operation}ed successfully"})
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to {operation} file: {e!s}",
            )

    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid operation. Use 'read', 'write', or 'append'",
        )


def get_syftbox_src_path():
    import importlib.util

    module_name = "syftbox"
    spec = importlib.util.find_spec(module_name)
    return spec.origin


def main() -> None:
    args = parse_args()
    client_config = load_or_create_config(args)

    os.environ["SYFTBOX_DATASITE"] = client_config.email
    os.environ["SYFTBOX_CLIENT_CONFIG_PATH"] = client_config.config_path

    print("Dev Mode: ", os.environ.get("SYFTBOX_DEV"))
    print("Wheel: ", os.environ.get("SYFTBOX_WHEEL"))

    debug = True
    uvicorn.run(
        "syftbox.client.client:app"
        if debug
        else app,  # Use import string in debug mode
        host="0.0.0.0",
        port=client_config.port,
        log_level="debug" if debug else "info",
        reload=debug,  # Enable hot reloading only in debug mode
        reload_dirs="./syftbox",
    )


if __name__ == "__main__":
    main()
