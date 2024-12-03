from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from syftbox.lib.email import send_token_email
from syftbox.server.analytics import log_analytics_event
from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.users.auth import delete_token, generate_access_token, generate_email_token, get_user_from_email_token, get_current_user, set_token
from syftbox.server.users.user_store import User, UserStore

router = APIRouter(prefix="/auth", tags=["authentication"])


class EmailTokenRequest(BaseModel):
    email: EmailStr

class EmailTokenResponse(BaseModel):
    email_token: Optional[str] = None

class AccessTokenResponse(BaseModel):
    access_token: str


@router.post("/request_email_token")
def get_token(req: EmailTokenRequest, server_settings: ServerSettings = Depends(get_server_settings)) -> EmailTokenResponse:
    """
    Send an email token to the user's email address

    if auth is disabled, the token will be returned in the response as a base64 encoded json string
    """
    email = req.email
    token = generate_email_token(server_settings, email)

    user_store = UserStore(server_settings=server_settings)
    if not user_store.exists(email=email):
        user_store.add_user(User(email=email, credentials=""))
    else:
        user_store.update_user(User(email=email, credentials=""))
    
    response = EmailTokenResponse()
    if server_settings.auth_enabled:
        send_token_email(server_settings, email, token)
    else:
        # Only return token if auth is disabled, it will be a base64 encoded json string
        response.email_token = token

    return response


@router.post("/validate_email_token")
def validate_email_token(
    email: str,
    email_from_token: str = Depends(get_user_from_email_token),
    server_settings: ServerSettings = Depends(get_server_settings),
) -> AccessTokenResponse:
    """
    Validate the email token and return a matching access token

    Args:
        email (str, optional): The user email, extracted from the email token. Defaults to Depends(get_user_from_email_token).
        server_settings (ServerSettings, optional): server settings. Defaults to Depends(get_server_settings).

    Returns:
        AccessTokenResponse: access token
    """
    user_store = UserStore(server_settings=server_settings)
    user = user_store.get_user_by_email(email=email)
    access_token = generate_access_token(server_settings, email)
    if user:
        if user.credentials is not None:
            set_token(server_settings, email, access_token)
        else:
            # what happens if there is already some credentials set?
            # it looks like if someone steals the email token, they can generate the access token
            pass 
    else:
        raise HTTPException(status_code=404, detail="User not found! Please register")
    return AccessTokenResponse(access_token=access_token)

class WhoAmIResponse(BaseModel):
    email: str

@router.post("/invalidate_access_token")
def invalidate_access_token(
    email: str = Depends(get_current_user),
    server_settings: ServerSettings = Depends(get_server_settings),
) -> str:
    """
    Invalidate the access token/

    Args:
        email (str, optional): The user email, extracted from the access token in the Authorization header.
            Defaults to Depends(get_current_user).

        server_settings (ServerSettings, optional): server settings. Defaults to Depends(get_server_settings).

    Returns:
        str: message
    """
    delete_token(server_settings, email)
    return "Token invalidation succesful!"


@router.post("/whoami")
def whoami(
    email: str = Depends(get_current_user),
) -> WhoAmIResponse:
    """
    Get the current users email.
    If the token is not valid or outdated, get_current_user will raise 401 Unauthorized.

    Returns:
        str: email
    """
    log_analytics_event("/auth/whoami", email=email)
    return WhoAmIResponse(email=email)