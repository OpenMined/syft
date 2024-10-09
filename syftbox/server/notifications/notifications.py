import jinja2

from syftbox.server.users.user import User

from ..users.user import User
from .email_templates import create_token_email

jinja_env = jinja2.Environment(loader=jinja2.PackageLoader("syftbox", "server/templates/email"))


def create_token_email(user: User) -> str:
    template = jinja_env.get_template("token_email.html")
    return template.render(email=user.email, token=user.token)


def send_token_email(user: User) -> None:
    email_body = create_token_email(user)
