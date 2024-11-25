from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

router = APIRouter()

jinja_env = Environment(loader=FileSystemLoader("syftbox/assets/templates"))


@router.get("/")
def sync_dashboard():
    template = jinja_env.get_template("sync_dashboard.jinja2")
    return HTMLResponse(template.render())
