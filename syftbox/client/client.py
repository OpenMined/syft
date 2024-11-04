import argparse
import atexit
import contextlib
import importlib
import importlib.util
import os
import platform
import subprocess
import sys
import time
import types
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

import crossplane
import uvicorn
import yaml
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel, create_model
from typing_extensions import Any, Optional
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from syftbox import __version__
from syftbox.client.plugins.sync.manager import SyncManager
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
    shared_state: SharedState
    job_file: str
    watchdog: Any
    job_file: str


current_dir = Path(__file__).parent
proxy_file = current_dir / "../../proxy/client_nginx.conf"
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


def initialize_shared_state(client_config: ClientConfig) -> SharedState:
    shared_state = SharedState(client_config=client_config)
    return shared_state


def load_plugins(client_config: ClientConfig) -> dict[str, Plugin]:
    loaded_plugins = {}
    if os.path.exists(PLUGINS_DIR) and os.path.isdir(PLUGINS_DIR):
        for item in os.listdir(PLUGINS_DIR):
            if item.endswith(".py") and not item.startswith("__") and "sync" not in item:
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
    if "sync" in plugin_name:
        return

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
    parser.add_argument("--config_path", type=str, default=DEFAULT_CONFIG_PATH, help="config path")

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

    parser.add_argument("--no_open_sync_folder", action="store_true", help="no open sync folder")

    subparsers = parser.add_subparsers(dest="command", help="Sub-command help")
    start_parser = subparsers.add_parser("report", help="Generate an error report")
    start_parser.add_argument(
        "--path",
        type=str,
        help="Path to the error report file",
        default=f"./syftbox_logs_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}",
    )

    return parser.parse_args()


app = FastAPI()
loaded_routes = {}
watched_files = {}
observer = Observer()


def load_python_file(file_path: str):
    """
    Loads a Python file as a module and returns the module object.
    """
    try:
        file_path = Path(file_path).resolve()
        module_name = file_path.stem  # Use the file name (without extension) as the module name

        # Create a module specification from the file location
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        with open(file_path) as f:
            data = f.read()
            print("CODE", data)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(f"Loaded module: {module}")
            return module
        else:
            raise HTTPException(status_code=500, detail=f"Could not load module from {file_path}")

    except Exception as e:
        print(f"Failed to load module {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Error loading module {file_path}: {str(e)}")


def load_routes_from_yaml(yaml_path: str):
    """
    Loads routes from a YAML file and binds them to the FastAPI app or updates the Nginx configuration if the route is a service.
    """
    yaml_dir = Path(yaml_path).parent  # Get the directory of the YAML file
    route_path_parent = str(yaml_dir).split(str(app.shared_state.client_config.datasite_path))[-1]
    print("route_path_parent", route_path_parent)

    with open(yaml_path, "r") as file:
        route_config = yaml.safe_load(file)

    for route_path, route_info in route_config.get("routes", {}).items():
        # Check if the route is defined as a service
        if "service" in route_info:
            service_name = route_info["service"]
            route = route_path_parent
            port = route_info.get("port", 80)  # Default to port 80 if not specified
            print(f"Detected service route. Adding Nginx route for service '{service_name}' on port {port}.")

            # Call the function to add an Nginx route
            add_nginx_route(proxy_file, route, port)
            # Keep track of the added service route
            loaded_routes[yaml_path] = {
                "route_info": route_info,
                "route_path": f"{route}",
                "module_path": None,  # No Python file for a service route
            }
            continue  # Skip adding to FastAPI since it's an Nginx route

        # Ensure route_path starts with a leading slash for FastAPI routes
        if not route_path.startswith("/"):
            route_path = route_path_parent + "/" + route_path
        print("route_path", route_path)

        # Construct the full path to the Python file
        file_path = (yaml_dir / route_info["file"]).resolve()

        # Load the module using the helper function
        endpoint_module = load_python_file(str(file_path))

        # Add the Python module to the watched files list and set up a watcher if not already watched
        if str(file_path) not in watched_files:
            watched_files[str(file_path)] = yaml_path

        for method, method_info in route_info.get("methods", {}).items():
            # Create a Pydantic model for form validation if specified for the method
            form_model = None
            if "form" in method_info:
                form_fields = {
                    field_name: (eval(field_type), ...) for field_name, field_type in method_info["form"].items()
                }
                form_model = create_model(f"{route_path.strip('/').replace('/', '_')}_{method}_Form", **form_fields)

            # Define the route handler
            async def route_handler(request: Request, form_data: form_model = Depends() if form_model else None):
                if hasattr(endpoint_module, "handler"):
                    response = await endpoint_module.handler(request, form_data)
                    return response
                else:
                    raise HTTPException(
                        status_code=500, detail=f"Module {route_info['file']} does not have a 'handler' function"
                    )

            # Add the route to the FastAPI app
            app.add_api_route(route_path, route_handler, methods=[method], name=f"{route_path.strip('/')}_{method}")

        # Keep track of the added route path
        loaded_routes[yaml_path] = {"route_info": route_info, "route_path": route_path, "module_path": str(file_path)}


def remove_route(yaml_path: str):
    """
    Removes a route and its file watcher based on the specified YAML path.
    If the route is defined as a service, it calls `remove_route` for Nginx.
    Otherwise, it removes the route from the FastAPI app.
    """
    global loaded_routes, watched_files

    if yaml_path not in loaded_routes:
        raise ValueError(f"No routes found for {yaml_path}")

    route_info = loaded_routes[yaml_path]["route_info"]
    route_path = loaded_routes[yaml_path]["route_path"]
    module_path = loaded_routes[yaml_path]["module_path"]

    # Determine if the route is a service
    is_service = "service" in route_info

    if is_service:
        service_name = route_info["service"]
        print(f"Detected service route. Removing Nginx route for service '{service_name}'.")
        remove_nginx_route(proxy_file, service_name)
    else:
        print("Detected Python route. Removing FastAPI route.")
        # Remove route from FastAPI app
        print("Routes before removal:", [route.path for route in app.router.routes])
        app.router.routes = [route for route in app.router.routes if route.path != route_path]
        print("Routes after removal:", [route.path for route in app.router.routes])

    # Remove the Python file from the watched files list if present
    if module_path in watched_files:
        del watched_files[module_path]

    # Remove the route from the loaded routes dictionary
    del loaded_routes[yaml_path]

    print(f"Route removed for path: {route_path}")


def update_route(yaml_path: str):
    print("calling update route on", yaml_path)
    """
    Updates a route by removing the old route and reloading it from the YAML path.
    """
    try:
        print("removing file?")
        remove_route(yaml_path)
    except ValueError:
        print("did remove fail?")
        pass  # Route may not exist yet, so ignore error
    load_routes_from_yaml(yaml_path)


def add_route_watcher(datasite_path: str):
    """
    Adds a watcher to monitor changes in the routes YAML files and their associated Python modules.
    """

    class RouteChangeHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.src_path.endswith("routes.yaml"):
                update_route(event.src_path)
            elif event.src_path in watched_files:
                print(f"Detected change in watched file: {event.src_path}")
                # Find and reload any YAML that references this file
                for yaml_path, route_data in list(loaded_routes.items()):  # Use a static copy for safe iteration
                    if event.src_path == route_data["module_path"]:
                        update_route(yaml_path)

        def on_deleted(self, event):
            if event.src_path.endswith("routes.yaml"):
                try:
                    remove_route(event.src_path)
                except ValueError:
                    pass  # Ignore if route was not previously loaded
            elif event.src_path in watched_files:
                print(f"Detected deletion of watched file: {event.src_path}")
                # Remove related routes if a Python module is deleted
                for yaml_path, route_data in list(loaded_routes.items()):  # Use a static copy for safe iteration
                    if event.src_path == route_data["module_path"]:
                        remove_route(yaml_path)

        def on_modified(self, event):
            if event.src_path.endswith("routes.yaml"):
                update_route(event.src_path)
            elif event.src_path in watched_files:
                print(f"Detected modification in watched file: {event.src_path}")
                # Find and reload any YAML that references this file
                for yaml_path, route_data in list(loaded_routes.items()):  # Use a static copy for safe iteration
                    if event.src_path == route_data["module_path"]:
                        update_route(yaml_path)

    event_handler = RouteChangeHandler()
    observer.schedule(event_handler, datasite_path, recursive=True)
    observer.start()

    # Run the observer in a background thread
    def stop_observer_on_shutdown():
        observer.stop()
        observer.join()

    app.add_event_handler("shutdown", stop_observer_on_shutdown)


def parse_nginx_conf(nginx_conf_path):
    """
    Parses the existing NGINX configuration file and returns the parsed structure.
    """
    payload = crossplane.parse(nginx_conf_path)
    if payload["status"] != "ok" or not payload["config"]:
        raise Exception(f"Error parsing NGINX config: {payload['errors']}")
    return payload["config"][0]["parsed"]


def save_nginx_conf(nginx_conf_path, parsed_config):
    """
    Saves the modified configuration back to the NGINX configuration file.
    """
    modified_config = crossplane.build(parsed_config)
    with open(nginx_conf_path, "w") as f:
        f.write(modified_config)
    print(f"Updated configuration saved to {nginx_conf_path.resolve()}")


def add_nginx_route(nginx_conf_path, route, port):
    """
    Adds a new route to the NGINX configuration.
    """
    parsed_config = parse_nginx_conf(nginx_conf_path)
    route_path = f"/{route}".replace("//", "/")

    new_location_block = {
        "directive": "location",
        "args": [route_path],
        "block": [
            {"directive": "proxy_pass", "args": [f"http://host.docker.internal:{port}"]},
            {"directive": "proxy_set_header", "args": ["Host", "$host"]},
            {"directive": "proxy_set_header", "args": ["X-Real-IP", "$remote_addr"]},
            {"directive": "proxy_set_header", "args": ["X-Forwarded-For", "$proxy_add_x_forwarded_for"]},
            {"directive": "proxy_set_header", "args": ["X-Forwarded-Proto", "$scheme"]},
        ],
    }

    for block in parsed_config:
        if block["directive"] == "http":
            for sub_block in block["block"]:
                if sub_block["directive"] == "server":
                    existing_locations = [
                        loc["args"][0] for loc in sub_block["block"] if loc["directive"] == "location"
                    ]
                    if route_path not in existing_locations:
                        sub_block["block"].append(new_location_block)
                        print(f"Added new location block for {route_path}")
                        save_nginx_conf(nginx_conf_path, parsed_config)
                        return
                    else:
                        print(f"Location block for {route_path} already exists.")
                        return


def remove_nginx_route(nginx_conf_path, service_name):
    """
    Removes a route from the NGINX configuration.
    """
    parsed_config = parse_nginx_conf(nginx_conf_path)

    for block in parsed_config:
        if block["directive"] == "http":
            for sub_block in block["block"]:
                if sub_block["directive"] == "server":
                    sub_block["block"] = [
                        loc
                        for loc in sub_block["block"]
                        if not (loc["directive"] == "location" and loc["args"][0] == f"/{service_name}")
                    ]
                    print(f"Removed location block for /{service_name}")
                    save_nginx_conf(nginx_conf_path, parsed_config)
                    return

    print(f"Location block for /{service_name} not found.")


@contextlib.asynccontextmanager
async def lifespan(app: CustomFastAPI, client_config: Optional[ClientConfig] = None):
    # Startup
    logger.info(f"> Starting SyftBox Client: {__version__} Python {platform.python_version()}")

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

    print("> client_config.datasite_path", client_config.datasite_path)
    for yaml_file in Path(client_config.datasite_path).rglob("routes.yaml"):
        print("YAML FILE", yaml_file)
        update_route(str(yaml_file))
    add_route_watcher(client_config.datasite_path)

    logger.info(f"Connecting to {client_config.server_url}")

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
    logger.info(f"> Loaded plugins: {sorted(list(app.loaded_plugins.keys()))}")

    logger.info(f"> Starting autorun plugins: {sorted(client_config.autorun_plugins)}")
    for plugin in client_config.autorun_plugins:
        start_plugin(app, plugin)

    start_syncing(app)

    yield  # This yields control to run the application

    logger.info("> Shutting down...")
    scheduler.shutdown()
    if close_client_config:
        client_config.close()


def start_syncing(app: CustomFastAPI):
    manager = SyncManager(app.shared_state.client_config)
    manager.start()


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

# @app.get("/")
# async def get_ascii_art(request: Request):
#     # Access and print headers to the console
#     headers = dict(request.headers)
#     print(json.dumps(headers, indent=4))  # Print headers to the console/logs

#     # Optionally return headers as response to inspect via the browser or curl
#     return {"message": "your local syftbox mirror", "headers": headers}


@app.get("/routes-info")
async def get_loaded_routes_info():
    routes_info = []
    for route in app.router.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            routes_info.append({"path": route.path, "methods": list(route.methods), "name": route.name})
    return {"loaded_routes": routes_info}


@app.get("/")
async def test(request: Request):
    return "test"


def main() -> None:
    args = parse_args()
    client_config = load_or_create_config(args)
    if not args.no_open_sync_folder:
        pass
        # open_sync_folder(client_config.sync_folder)
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

    logger.info(f"Dev Mode:  {os.environ.get('SYFTBOX_DEV')}")
    logger.info(f"Wheel: {os.environ.get('SYFTBOX_WHEEL')}")

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

# TODO: fix remove routes to use route not service name
# bind to service name and supply random port
# force overwrite add so that ports change etc
# nginx conf in correct order
# rewrite ^/bigquery/?(.*)$ /$1 break;
