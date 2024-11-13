from typing_extensions import Annotated
from fastapi import Depends, HTTPException, Header, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

from syftbox.server.settings import ServerSettings, get_server_settings

class AuthenticationError(Exception):
    pass

bearer_scheme = HTTPBearer()

def get_user_manager():
    return UserManager()

class UserManager:
    def __init__(self, server_settings: ServerSettings):
        self.server_settings = server_settings

    def validate_token(self, access_token: str):
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        resp = httpx.post(f"{self.server_settings.keycloak_url}/realms/master/protocol/openid-connect/userinfo", headers=headers)
        resp.raise_for_status()
        # TODO check email verification
        return resp.json()



def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    server_settings: Annotated[ServerSettings, Depends(get_server_settings)],
    email: Annotated[str | None, Header()] = None,
) -> str:
    if server_settings.auth_disabled:
        if email is None:
            raise AuthenticationError("email is required in header when auth is disabled.")
        return email


    try:
        user = user_manager.validate_token(credentials.credentials)
        return user['email']
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.reason_phrase,
            headers={"WWW-Authenticate": "Bearer"},
        )


