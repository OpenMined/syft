import argparse
import atexit
import contextlib
import importlib
import os
import platform
import sys
import time
import types
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
import subprocess

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
from loguru import logger
from pydantic import BaseModel
from typing_extensions import Any

from syftbox import __version__
from syftbox.client.utils.error_reporting import make_error_report
from syftbox.lib import (
    DEFAULT_CONFIG_PATH,
    ClientConfig,
    SharedState,
    load_or_create_config,
)
from syftbox.lib.logger import zip_logs


class CustomFastAPI(FastAPI):
    loaded_plugins: dict
    running_plugins: dict
    scheduler: Any
    shared_state: dict
    job_file: str
    watchdog: Any
    job_file: str


current_dir = Path(__file__).parent
# Initialize FastAPI app and scheduler

templates = Jinja2Templates(directory=str(current_dir / "templates"))


PLUGINS_DIR = current_dir / "plugins"
sys.path.insert(0, os.path.dirname(PLUGINS_DIR))

DEFAULT_SYNC_FOLDER = os.path.expanduser("~/Desktop/SyftBox")


ASSETS_FOLDER = current_dir.parent / "assets"
ICON_FOLDER = ASSETS_FOLDER / "icon"

WATCHDOG_IGNORE = ["apps"]


@dataclass
class Plugin:
    name: str
    module: types.ModuleType
    schedule: int
    description: str


def open_sync_folder(folder_path):
    """Open the folder specified by `folder_path` in the default file explorer."""
    logger.info(f"Opening your sync folder: {folder_path}")
    try:
        if platform.system() == "Darwin":  # macOS
            subprocess.run(["open", folder_path])
        elif platform.system() == "Windows":  # Windows
            subprocess.run(["explorer", folder_path])
        elif platform.system() == "Linux":  # Linux
            subprocess.run(["xdg-open", folder_path])
        else:
            logger.warning(f"Unsupported OS for opening folders: {platform.system()}")
    except Exception as e:
        logger.error(f"Failed to open folder {folder_path}: {e}")

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
                    logger.info(e)

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
        logger.exception(e)


def start_plugin(app: CustomFastAPI, plugin_name: str):
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
            logger.info(f"Job {existing_job}, already added")
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

    parser.add_argument("--debug", action="store_true", help="debug mode")

    parser.add_argument("--sync_folder", type=str, help="sync folder path")
    parser.add_argument("--email", type=str, help="email")
    parser.add_argument("--port", type=int, default=8080, help="Port number")
    parser.add_argument(
        "--server",
        type=str,
        default="https://syftbox.openmined.org",
        help="Server",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-command help")
    start_parser = subparsers.add_parser("report", help="Generate an error report")
    start_parser.add_argument(
        "--path",
        type=str,
        help="Path to the error report file",
        default=f"./syftbox_logs_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}",
    )

    return parser.parse_args()


# def start_watchdog(app) -> FSWatchdog:
#     def sync_on_event(event: FileSystemEvent):
#         run_plugin("sync", event)

#     watch_dir = Path(app.shared_state.client_config.sync_folder)
#     watch_dir.mkdir(parents=True, exist_ok=True)
#     event_handler = AnyFileSystemEventHandler(
#         watch_dir,
#         callbacks=[sync_on_event],
#         ignored=WATCHDOG_IGNORE,
#     )
#     watchdog = FSWatchdog(watch_dir, event_handler)
#     watchdog.start()
#     return watchdog


@contextlib.asynccontextmanager
async def lifespan(app: CustomFastAPI, client_config: ClientConfig | None = None):
    # Startup
    logger.info(
        f"> Starting SyftBox Client: {__version__} Python {platform.python_version()}"
    )

    config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH")
    if config_path:
        client_config = ClientConfig.load(config_path)

    # client_config needs to be closed if it was created in this context
    # if it is passed as lifespan arg (eg for testing) it should be managed by the caller instead.
    close_client_config: bool = False
    if client_config is None:
        args = parse_args()
        client_config = load_or_create_config(args)
        close_client_config = True
    app.shared_state = SharedState(client_config=client_config)

    # Clear the lock file on the first run if it exists
    job_file = client_config.config_path.replace(".json", ".sql")
    app.job_file = job_file
    if os.path.exists(job_file):
        os.remove(job_file)
        logger.info(f"> Cleared existing job file: {job_file}")

    # Start the scheduler
    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{job_file}")}
    scheduler = BackgroundScheduler(jobstores=jobstores)
    scheduler.start()
    atexit.register(partial(stop_scheduler, app))

    app.scheduler = scheduler
    app.running_plugins = {}
    app.loaded_plugins = load_plugins(client_config)
    logger.info("> Loaded plugins:", sorted(list(app.loaded_plugins.keys())))
    # app.watchdog = start_watchdog(app)

    logger.info("> Starting autorun plugins:", sorted(client_config.autorun_plugins))
    for plugin in client_config.autorun_plugins:
        start_plugin(app, plugin)

    yield  # This yields control to run the application

    logger.info("> Shutting down...")
    scheduler.shutdown()
    # app.watchdog.stop()
    if close_client_config:
        client_config.close()


def stop_scheduler(app: FastAPI):
    # Remove the lock file if it exists
    if os.path.exists(app.job_file):
        os.remove(app.job_file)
        logger.info("> Scheduler stopped and lock file removed.")


app: CustomFastAPI = FastAPI(lifespan=lifespan)

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
def launch_plugin(plugin_request: PluginRequest, request: Request):
    return start_plugin(request.app, plugin_request.plugin_name)


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
    open_sync_folder(client_config.sync_folder)
    error_config = make_error_report(client_config)

    if args.command == "report":
        output_path = Path(args.path).resolve()
        output_path_with_extension = zip_logs(output_path)
        logger.info(f"Logs saved to: {output_path_with_extension}.")
        logger.info("Please share your bug report together with the zipped logs")
        return

    logger.info(f"Client metadata: {error_config.model_dump_json(indent=2)}")

    os.environ["SYFTBOX_DATASITE"] = client_config.email
    os.environ["SYFTBOX_CLIENT_CONFIG_PATH"] = client_config.config_path

    logger.info("Dev Mode: ", os.environ.get("SYFTBOX_DEV"))
    logger.info("Wheel: ", os.environ.get("SYFTBOX_WHEEL"))

    debug = True if args.debug else False
    port = client_config.port
    max_attempts = 10  # Maximum number of port attempts

    for attempt in range(max_attempts):
        try:
            uvicorn.run(
                "syftbox.client.client:app" if debug else app,
                host="0.0.0.0",
                port=port,
                log_level="debug" if debug else "info",
                reload=debug,
                reload_dirs="./syftbox",
            )
            return  # If successful, exit the loop
        except SystemExit as e:
            if e.code != 1:  # If it's not the "Address already in use" error
                raise
            logger.info(f"Failed to start server on port {port}. Trying next port.")
            port = 0
    logger.info(f"Unable to find an available port after {max_attempts} attempts.")
    sys.exit(1)


if __name__ == "__main__":
    main()
