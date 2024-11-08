import json
from typing import Annotated, Any, List
import fastapi
from fastapi import Depends, HTTPException, Header, Request
from pydantic import BaseModel
import requests

from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.users.auth import create_access_token

# from .auth import verify_admin_credentials, verify_current_user
from .user import User, UserManager, UserUpdate
from syftbox.server.users.secret_constants import CLIENT_ID, CLIENT_SECRET, KEYCLOAK_REALM, KEYCLOAK_URL, ADMIN_UNAME, ADMIN_PASSWORD

user_router = fastapi.APIRouter(
    prefix="/users",
    tags=["users"],
)


def notify_user(user: User) -> None:
    print(f"New token {user.email}: {user.token}")


# def get_user_by_email(email: str, user_manager: UserManager = Depends(get_user_manager)) -> User:
#     user = user_manager.get_user(email)
#     if user is None:
#         raise HTTPException(status_code=404, detail="User not found")
#     return user

def create_admin_token() -> str:
    return create_access_token(ADMIN_UNAME, ADMIN_PASSWORD)

def get_user_by_token(token: str):
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    resp = requests.post(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/userinfo", headers=headers)
    content = json.loads(resp.text)
    return content

def get_admin_user(token: str):
    user = get_user_by_token(create_admin_token())
    return user

# @user_router.post("/register_tokens")
# async def register_tokens(
#     emails: list[str],
#     user_manager: UserManager = Depends(get_user_manager),
#     is_admin: bool = Depends(verify_admin_credentials),
# ) -> list[User]:
#     """
#     Register tokens for a list of emails.
#     All users are created in the db with a random token, and an email is sent to each user.

#     If the user already exists, the existing user is notified again with the same token.

#     Args:
#         emails (list[str]): list of emails to register.
#         is_admin (bool, optional): checks if the user is an admin.
#         user_manager (UserManager, optional): the user manager. Defaults to Depends(get_user_manager).

#     Returns:
#         list[User]: list of users created.
#     """
#     users = []
#     for email in emails:
#         user = user_manager.create_token_for_user(email)
#         users.append(user)
#         notify_user(user)

#     return users


# @user_router.post("/update")
# async def update(
#     user_update: UserUpdate,
#     user: User = Depends(get_user_by_email),
#     is_admin: bool = Depends(verify_admin_credentials),
#     user_manager: UserManager = Depends(get_user_manager),
# ) -> User:
#     user_update_dict = user_update.model_dump(exclude_unset=True)
#     updated_user = user.model_copy(update=user_update_dict)
#     result = user_manager.update_user(updated_user)
#     return result


class RegisterResponse(BaseModel):
    bearer_token: str

def get_headers():
    admin_token = create_admin_token()
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
    return requests.post(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users", headers=get_headers(), data=json.dumps(userdata))

def send_action_email(user_id: str, actions: List[str]):
    return requests.put(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/execute-actions-email?client_id={CLIENT_ID}", 
                headers=get_headers(), 
                data=json.dumps(actions)
            )
    

def get_users():
    resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/", headers=get_headers())
    if resp.status_code == 200:
        content = resp.json()
        return content
    return resp.text


@user_router.post('/test')
async def test(
    # token: str,
    token: Annotated[str | None, Header()],
    # user: Any = Depends(get_user_by_token),
    # user_manager: UserManager = Depends(get_user_manager),
) -> str:
    return token

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
    print("> error?")
    return resp

def update_user(user_id, payload):
    return requests.get(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}", headers=get_headers(), data=json.dumps(payload))


def ban_user(user):
    user_id = user['id']
    payload = {
        "isBanned": True
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
    
# @user_router.post("/register")
# async def register(
#     token: str,
#     user: User = Depends(get_user_by_email),
#     user_manager: UserManager = Depends(get_user_manager),
#     server_settings: ServerSettings = Depends(get_server_settings),
# ) -> RegisterResponse:
#     """Endpoint used by the user to register. This only works if the user has the correct token.
#     Returns a bearer token that can be used to authenticate the user.

#     Args:
#         email (str): user email
#         token (str): user token, generated by /register_tokens
#     """
#     if user.token != token:
#         raise HTTPException(status_code=404, detail="Invalid token")

#     updated_user = user.model_copy(update={"is_registered": True})
#     user_manager.update_user(updated_user)

#     bearer_token = create_access_token(user, server_settings)
#     return RegisterResponse(bearer_token=bearer_token)
