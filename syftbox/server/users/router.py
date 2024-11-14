from typing import Any, List
import fastapi
from fastapi import Depends
from pydantic import BaseModel
import requests
import json

from syftbox.lib.keycloak import CLIENT_ID, CLIENT_SECRET, KEYCLOAK_REALM, KEYCLOAK_URL, send_action_email, update_user
from syftbox.server.users.auth2 import UserManager, get_user_manager

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




def create_user(email, firstName, lastName, password):
    print(f"> {email}, {firstName}, {lastName}, {password}")
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






def delete_user(user_id):
    resp = requests.delete(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}", headers=get_admin_headers())
    if resp.status_code != 200:
        print(f"> error {resp.status_code} {resp.text}")
    return resp




def remove_user_files(user):
    print(user['email'].split("@")[0])

class User(BaseModel):
    email: str
    password: str


@user_router.post("/register")
async def register(
    user: User,
    user_manager: UserManager = Depends(get_user_manager)
) -> str:
    email = user.email
    password = user.password
    resp = create_user(email=email, password=password)
    resp.raise_for_status()
    # Keycloak does not return the id of the user just created
    user = user_manager.get_details(email)

    user_id = user['id']
    actions = ["UPDATE_PASSWORD"]
    resp = send_action_email(user_id=user_id, actions=actions)
    print(resp.status_code, resp.text)
    return "Email sent!"
    print(f"> error? {resp.status_code} {resp.text} ")
    return resp


def ban_user(user):
    user_id = user['id']
    payload = {
        "enabled": False
    }
    return update_user(user_id, payload)

@user_router.post('/ban')
async def ban(
    email_to_ban: str,
    user_manager: UserManager = Depends(get_user_manager)
) -> str:
    user = user_manager.get_details(email_to_ban)
    resp = user_manager.ban_user(user)
    remove_user_files(user)
    return "User Banned"
    return "User Not Found"