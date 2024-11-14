import datetime
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
class KeycloakUser(BaseModel):
    data : dict[str, Any] = Field(description="The raw data from the Keycloak API")
    id : str
    username : str
    email : str
    email_verified : bool =Field(alias='emailVerified')
    created_timestamp : datetime.datetime = Field(alias='createdTimestamp')

    def is_new(self):
        # new if created within 24 hours
        return (datetime.datetime.now(datetime.UTC) - self.created_timestamp).days < 1

bearer_scheme = HTTPBearer()



class UserManager:
    def __init__(self, server_settings: ServerSettings, access_token: str):
        self.server_settings = server_settings
        self.url = self.server_settings.keycloak_url
        self.realm = self.server_settings.keycloak_realm

        self.client = httpx.Client(
            base_url=self.url,
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
        )


    def create_user(self, email, password):
        userdata = {
            "email": email,
            "enabled": "true",
            "username": email,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        return self.client(
            f"/admin/realms/{self.realm}/users", data=userdata
        )

    def validate_token(self):
        resp = self.client.post(f"/realms/{self.realm}/protocol/openid-connect/userinfo")
        resp.raise_for_status()

        user_info = KeycloakUserInfoResponse(**resp.json())

        if not user_info.email_verified:
            # If email is not verified, we give user 24 hours to verify it
            user_details = self.get_details(user_info.email)
            if not user_details.is_new():
                raise AuthenticationError("Email not verified")

        return user_info

    def get_details(self, email: str) -> KeycloakUser:
        resp = self.client.get(f"/admin/realms/{self.realm}/users", params={"email": email})
        resp.raise_for_status()
        data = resp.json()
        if len(data) != 1:
            logger.error(f"Expected 1 user, got {len(data)}, {data}")
            raise AuthenticationError(f"User not found: {email}")
        repr_dict = data[0]
        user_repr = KeycloakUser(data=repr_dict, **repr_dict)
        return user_repr

def get_user_manager(
    server_settings: Annotated[ServerSettings, Depends(get_server_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
) -> UserManager:
    return UserManager(server_settings, credentials.credentials)

def get_current_user(
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    email: Annotated[str | None, Header()] = None,
) -> str:
    if user_manager.server_settings.no_auth:
        if email is None:
            raise AuthenticationError("email is required in header when auth is disabled.")
        return email


    try:
        user_info = user_manager.validate_token()
        return user_info.email
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.reason_phrase,
            headers={"WWW-Authenticate": "Bearer"},
        )


