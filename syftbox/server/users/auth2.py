from datetime import datetime
from typing import Any
from loguru import logger
from pydantic import BaseModel, Field
from typing_extensions import Annotated
from fastapi import Depends, HTTPException, Header, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

from syftbox.server.settings import ServerSettings, get_server_settings

class AuthenticationError(Exception):
    pass

class KeycloakUserInfoResponse(BaseModel):
    sub: str
    email_verified: bool
    preferred_username: str
    email: str


# https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation
class KeycloakUserRepresentation(BaseModel):
    data : dict[str, Any] = Field(description="The raw data from the Keycloak API")
    id : str
    username : str
    email : str
    email_verified : bool =Field(alias='emailVerified')
    created_timestamp : datetime = Field(alias='createdTimestamp')

    def is_new(self):
        # new if created within 24 hours
        return (datetime.now() - self.created_timestamp).days < 1

bearer_scheme = HTTPBearer()

def get_user_manager(server_settings: Annotated[ServerSettings, Depends(get_server_settings)]):
    return UserManager(server_settings)

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

        user_info = KeycloakUserInfoResponse(**resp.json())
        if not user_info.email_verified:
            # If email is not verified, we give user 24 hours to verify it
            user_details = self.get_details(headers, user_info)
            if not user_details.is_new():
                raise AuthenticationError("Email not verified")
        return user_info

    def get_details(self, headers: dict, user_info: KeycloakUserInfoResponse) -> KeycloakUserRepresentation:
        resp = httpx.get(f"{self.server_settings.keycloak_url}/admin/realms/master/users", headers=headers, params={"email": user_info.email})
        resp.raise_for_status()
        data = resp.json()
        if len(data) != 1:
            logger.error(f"Expected 1 user, got {len(data)}, {data}")
            raise AuthenticationError(f"User not found: {user_info.email}")
        repr_dict = data[0]
        user_repr = KeycloakUserRepresentation(data=repr_dict, **repr_dict)
        return user_repr


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    email: Annotated[str | None, Header()] = None,
) -> str:
    if user_manager.server_settings.no_auth:
        if email is None:
            raise AuthenticationError("email is required in header when auth is disabled.")
        return email


    try:
        user_info = user_manager.validate_token(credentials.credentials)
        return user_info.email
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.reason_phrase,
            headers={"WWW-Authenticate": "Bearer"},
        )


