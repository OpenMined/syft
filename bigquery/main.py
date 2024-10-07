import os

import uvicorn
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2AuthorizationCodeBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from syftbox.lib import ClientConfig

config_path = os.environ.get("SYFTBOX_CLIENT_CONFIG_PATH", None)
client_config = ClientConfig.load(config_path)


app = FastAPI()

# Add Session Middleware (Required for OAuth)
app.add_middleware(SessionMiddleware, secret_key="!secret")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

CLIENT_ID = ""
CLIENT_SECRET = ""

ACCESS_TOKEN_EXPIRE_MINUTES = 30

GOOGLE_CALLBACK_URL = "http://localhost:9081/auth/google/callback"

oauth2_google = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://accounts.google.com/o/oauth2/v2/auth",
    tokenUrl="https://accounts.google.com/o/oauth2/v2/token",
)

# Google OAuth configuration
oauth = OAuth()
oauth.register(
    name="google",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# User model
class User(BaseModel):
    email: str
    name: str


# JWT secret and algorithm
SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"


# Helper function to create JWT tokens
def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user_from_cookie(request: Request) -> dict | None:
    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        name: str = payload.get("name")
        if email is None or name is None:
            return None
        return {"email": email, "name": name}
    except JWTError:
        return None


@app.get("/")
async def home(request: Request, user: dict = Depends(get_current_user_from_cookie)):
    logged_in_html = ""
    if user:
        logged_in_html = f'Hello {user["name"]}, <a href="/logout">Logout</a>'
    else:
        logged_in_html = '<a href="/auth/google">Login</a>'

    output = f"""
<h1>Big Query</h1>
{logged_in_html}
<br />
<a href="/users/me">Account</a>
</br>
<a href="/sql">Submit SQL</a>
"""

    return HTMLResponse(output)


@app.get("/sql", response_class=HTMLResponse)
async def get_sql_page(request: Request):
    return templates.TemplateResponse("submit_sql.html", {"request": request})


@app.post("/submit-sql")
async def submit_sql(sql_query: str = Form(...)):
    # Process the SQL query here (e.g., send it to BigQuery)
    return {"message": "SQL query submitted", "sql_query": sql_query}


# Google login route to redirect the user to Google's OAuth login page
@app.get("/auth/google")
async def google_login(request: Request):
    redirect_uri = GOOGLE_CALLBACK_URL
    return await oauth.google.authorize_redirect(request, redirect_uri)


# Callback route to handle Google OAuth callback and get user info
@app.get("/auth/google/callback")
async def google_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token["userinfo"]
    email = userinfo["email"]
    name = userinfo["name"]

    if not email:
        raise HTTPException(status_code=400, detail="Failed to fetch email from Google")

    # Generate JWT token for the user
    access_token = create_access_token({"sub": email, "name": name})

    response = RedirectResponse(url="/")
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    return response


@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/")
    # Clear the cookie by setting it with an empty value and expiry in the past
    response.delete_cookie(key="access_token")
    return response


@app.get("/users/me")
async def get_current_user(user: dict = Depends(get_current_user_from_cookie)):
    return {"email": user["email"], "name": user["name"]}


@app.get("/healthcheck")
async def healthcheck():
    return {"status": "healthy"}


def main() -> None:
    debug = True
    uvicorn.run(
        "main:app" if debug else app,
        host="0.0.0.0",
        port=9081,
        log_level="debug" if debug else "info",
        reload=debug,
        reload_dirs="./",
    )


if __name__ == "__main__":
    main()
