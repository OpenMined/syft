import json
from typing import Annotated, Any, List
import fastapi
from fastapi import Depends, HTTPException, Header, Request
from pydantic import BaseModel
import requests

from syftbox.client.client import get_user_info
from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.users.auth import create_keycloak_access_token

from .user import User, UserManager, UserUpdate
from syftbox.server.users.secret_constants import CLIENT_ID, CLIENT_SECRET, KEYCLOAK_REALM, KEYCLOAK_URL, ADMIN_UNAME, ADMIN_PASSWORD

user_router = fastapi.APIRouter(
    prefix="/users",
    tags=["users"],
)


def create_keycloak_admin_token() -> str:
    return create_keycloak_access_token(ADMIN_UNAME, ADMIN_PASSWORD)


class RegisterResponse(BaseModel):
    bearer_token: str


def get_admin_headers():
    admin_token = create_keycloak_admin_token()
    return {
        'Authorization': f'Bearer {admin_token}',
        'Content-Type': 'application/json'
    }

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

def get_users():
    resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/", headers=get_admin_headers())
    if resp.status_code == 200:
        content = resp.json()
        return content
    return resp.text


def get_user_from_header(token: Annotated[str, Header()]):
    user = get_user_info(token)
    if user is None or not user['enabled']:
        raise HTTPException(status_code=401, detail="User not found")
    return user
        
def get_admin_user(token: Annotated[str, Header()]):
    user = get_user_from_header(token)
    # check if the user is admin
    if user['email'] == ADMIN_UNAME:
        return user
    raise HTTPException(status_code=403, detail="User not admin")


def delete_user(user_id):
    resp = requests.delete(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}", headers=get_admin_headers())
    if resp.status_code != 200:
        print(f"> error {resp.status_code} {resp.text}")
    return resp


@user_router.post('/test')
async def test(
    user: Any = Depends(get_user_from_header)
) -> Any:
    return user

def remove_user_files(user):
    print(user['email'].split("@")[0])

class User(BaseModel):
    email: str
    password: str
    firstName: str
    lastName: str


@user_router.post("/register")
async def register(
    user: User
) -> str:
    email = user.email
    firstName = user.firstName
    lastName = user.lastName
    password = user.password
    resp = create_user(email=email, firstName=firstName, lastName=lastName, password=password)
    print(resp, type(resp))
    if resp.status_code in [200, 201]:
        # Keycloak does not return the id of the user just created, currently
        # iterating through all the users and check the username
        users = get_users()
        print(users)
        if isinstance(users, str):
            return users
        for user in users:
            if user['username'] == email:
                user_id = user['id']
                actions = ["UPDATE_PASSWORD"]
                resp = send_action_email(user_id=user_id, actions=actions)
                print(resp.status_code, resp.text)
                return "Email sent!"
        return f'error user {email} not found after creation'
    print(f"> error? {resp.status_code} {resp.text} ")
    return resp

def update_user(user_id, payload):
    return requests.get(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}", headers=get_admin_headers(), data=json.dumps(payload))


def ban_user(user):
    user_id = user['id']
    payload = {
        "enabled": False
    }
    return update_user(user_id, payload)
    
@user_router.post('/ban')
async def ban(
    email: str,
    admin_user: Any = Depends(get_admin_user)
) -> str:
    users = get_users()
    print(users)
    if isinstance(users, str):
        return users
    for user in users:
        if user['username'] == email:
            resp = ban_user(user)
            print(resp.status_code, resp.text)
            remove_user_files(user)
            return "User Banned"
    return "User Not Found"