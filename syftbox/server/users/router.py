from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from syftbox.lib.email import send_token_email
from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.users.auth import generate_access_token, generate_email_token, get_user_from_email_token, get_current_user

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

    response = EmailTokenResponse()
    if server_settings.auth_enabled:
        send_token_email(server_settings, email, token)
    else:
        # Only return token if auth is disabled, it will be a base64 encoded json string
        response.email_token = token

    return response


@router.post("/validate_email_token")
def validate_email_token(
    email: str = Depends(get_user_from_email_token),
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
    access_token = generate_access_token(server_settings, email)
    return AccessTokenResponse(access_token=access_token)

class WhoAmIResponse(BaseModel):
    email: str

@router.post("/whoami")
def whoami(
    email: str = Depends(get_current_user),
) -> WhoAmIResponse:
    """
    Get the current users email.
    If the token is not valid or outdated, get_current_user will raise 401 Unauthorized.

    Args:
        email (str, optional): The user email, extracted from the access token in the Authorization header.
            Defaults to Depends(get_current_user).

    Returns:
        str: email
    """
    return WhoAmIResponse(email=email)