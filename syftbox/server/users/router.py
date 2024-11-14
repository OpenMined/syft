from typing import Any, List
import fastapi
from fastapi import Depends
import httpx
from pydantic import BaseModel
import requests
import json

from syftbox.lib.keycloak import ADMIN_PASSWORD, ADMIN_UNAME, CLIENT_ID, CLIENT_SECRET, KEYCLOAK_REALM, KEYCLOAK_URL, send_action_email, update_user
from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.users.auth2 import User, UserManager, UserNotFoundError, get_user_manager

user_router = fastapi.APIRouter(
    prefix="/users",
    tags=["users"],
)




def get_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

def reset_password(user_id, new_password, token):
    data = {
        "type": "password",
        "temporary": False,
        "value": new_password
    }
    resp = requests.put(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/users/{user_id}/reset-password", headers=get_headers(token), data=data)
    return resp




def create_user(user: User):
    userdata = {
    'firstName': firstName,
    'lastName': lastName,
    'email': email,
    'enabled': "true",
    'username': email,
    "credentials":[{"type": "password", "value": password, "temporary": False}]
    }
    return requests.post(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users", headers=get_admin_headers(), data=json.dumps(userdata))

def send_action_email(user_id: str, actions: List[str]):
    return requests.put(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/execute-actions-email?client_id={CLIENT_ID}",
                headers=get_admin_headers(),
                data=json.dumps(actions)
            )




@user_router.post("/register")
def register(
    user: User,
    server_settings: ServerSettings = Depends(get_server_settings)
) -> str:
    admin_token = UserManager.get_access_token(server_settings, User(email=ADMIN_UNAME, password=ADMIN_PASSWORD))
    user_manager = UserManager(server_settings, admin_token)
    user_manager.create_user(user)

    user_details = user_manager.get_details(user.email)
    user_manager.send_action_email(user_id=user_details.id, actions=["UPDATE_PASSWORD"])
    access_token = UserManager.get_access_token(server_settings, user)
    # resp = send_action_email(user_id=user_id, actions=actions)
    return access_token



@user_router.post('/ban')
def ban(
    email_to_ban: str,
    user_manager: UserManager = Depends(get_user_manager)
):
    try:
        user = user_manager.get_details(email_to_ban)
        user_manager.ban_user(user)
    except httpx.HTTPStatusError as e:
        return {"status": "error", "message": e.response.json()}
    except UserNotFoundError:
        return {"status": "error", "message": "User not found"}
    # TODO remove user files
    return {"status": f"User {email_to_ban} banned"}

@user_router.post('/login')
def login(
    user: User,
    server_settings: ServerSettings = Depends(get_server_settings)
):
    return UserManager.get_access_token(server_settings, user)