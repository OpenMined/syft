import datetime
import json
from typing import Any, List
from loguru import logger
from pydantic import BaseModel, Field
from typing_extensions import Annotated
from fastapi import Depends, HTTPException, Header, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

from syftbox.lib.keycloak import CLIENT_ID, CLIENT_SECRET
from syftbox.server.settings import ServerSettings, get_server_settings

class AuthenticationError(Exception):
    pass

class UserNotFoundError(Exception):
    pass


class User(BaseModel):
    email: str
    password: str


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
    def __init__(self, server_settings: ServerSettings, access_token: str|None=None):
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

    def create_user(self, user:User):
        userdata = {
            "username": user.email,
            "email": user.email,
            "enabled": "true",
            "firstName": "",
            "lastName": "",
            "credentials": [{"type": "password", "value": user.password, "temporary": False}],
        }
        resp = self.client.post(
            f"/admin/realms/{self.realm}/users", data=json.dumps(userdata)
        )
        resp.raise_for_status()

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
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AuthenticationError(e.response.text) from e
        data = resp.json()
        if len(data) != 1:
            logger.error(f"Expected 1 user, got {len(data)}, {data}")
            raise UserNotFoundError()
        repr_dict = data[0]
        user_repr = KeycloakUser(data=repr_dict, **repr_dict)
        return user_repr

    def ban_user(self, user: KeycloakUser):
        """Raises HTTPError if user is not found or if there is an error"""
        resp = self.client.put(f"/admin/realms/{self.realm}/users/{user.id}", json={"enabled": False})
        resp.raise_for_status()

    def unban_user(self, user: KeycloakUser):
        """Raises HTTPError if user is not found or if there is an error"""
        resp = self.client.put(f"/admin/realms/{self.realm}/users/{user.id}", json={"enabled": True})
        resp.raise_for_status()

    def delete_user(self, user: KeycloakUser):
        """Raises HTTPError if user is not found or if there is an error"""
        resp = self.client.delete(f"/admin/realms/{self.realm}/users/{user.id}")
        resp.raise_for_status()

    def send_action_email(self, user_id: str, actions: List[str]):
        resp = self.client.put(
                f"/admin/realms/{self.realm}/users/{user_id}/execute-actions-email?client_id={CLIENT_ID}",
                data=json.dumps(actions)
            )
        resp.raise_for_status()


    @staticmethod
    def get_access_token(server_settings:ServerSettings, user:User) -> str:
        # TODO client id and secret should be stored in the server settings
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": user.email,
            "password": user.password,
            "grant_type": "password",
        }

        client = httpx.Client(
            base_url=server_settings.keycloak_url,
        )

        resp = client.post(f"/realms/{server_settings.keycloak_realm}/protocol/openid-connect/token", data=data)
        resp.raise_for_status()
        token = resp.json()["access_token"]
        return token


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


