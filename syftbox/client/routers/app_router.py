import subprocess
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing_extensions import List

from syftbox.client.routers.common import APIContext

router = APIRouter()


def parse_frontmatter(file_path):
    """
    Parses frontmatter YAML from a README.md file and returns it as a Python dictionary.

    Args:
        file_path (str): Path to the README.md file.

    Returns:
        dict: The parsed YAML frontmatter as a dictionary. If no frontmatter is found, returns an empty dict.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    # Check for YAML frontmatter boundaries
    if lines[0].strip() == "---":
        yaml_lines = []
        for line in lines[1:]:
            if line.strip() == "---":
                break
            yaml_lines.append(line)

        # Parse the YAML content
        frontmatter = yaml.safe_load("".join(yaml_lines))
        return frontmatter if frontmatter else {}
    else:
        return {}


class AppDetails(BaseModel):
    name: str
    version: str
    source: str
    home: str
    icon: str


def get_all_apps(apps_dir: str) -> List[AppDetails]:
    """
    Get all apps in the given directory.

    Args:
        apps_dir (str): Path to the directory containing the apps.

    Returns:
        list: A list of AppDetails objects.
    """
    apps = []
    for app_dir in Path(apps_dir).iterdir():
        if app_dir.is_dir():
            readme_path = app_dir / "README.md"
            if readme_path.exists():
                frontmatter = parse_frontmatter(readme_path)
                app = AppDetails(
                    name=frontmatter.get("name", app_dir.name),
                    version=frontmatter.get("version", "0.0.1"),
                    source=frontmatter.get("source", ""),
                    home=frontmatter.get("home", ""),
                    icon=frontmatter.get("icon", ""),
                )
                apps.append(app)

    return apps


@router.get("/")
async def index(ctx: APIContext):
    apps_dir = ctx.workspace.apps
    apps = get_all_apps(apps_dir)

    return JSONResponse(content=[app.model_dump() for app in apps])


@router.get("/status/{app_name}")
async def app_details(ctx: APIContext, app_name: str):
    apps_dir = ctx.workspace.apps
    apps = get_all_apps(apps_dir)
    for app in apps:
        if app_name == app.name:
            return JSONResponse(content=app.model_dump())
    return JSONResponse(status_code=404, content={"message": "App not found"})


class InstallRequest(BaseModel):
    source: str
    version: str


@router.post("/install")
async def install_app(request: InstallRequest):
    command = ["syftbox", "app", "install", request.source]
    try:
        # Run the command and capture output
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print(result.stderr, result.stdout)
        # If successful, return JSON payload indicating success
        return {
            "status": "success",
            "message": f"App {request.source} version {request.version} installed successfully.",
            "output": result.stdout,
        }

    except subprocess.CalledProcessError as e:
        # Handle command failure, return JSON with error details
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": f"Failed to install app {request.source}.", "output": e.stderr},
        )
