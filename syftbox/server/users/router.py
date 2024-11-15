from typing import Any
import fastapi
from fastapi import Depends
from pydantic import BaseModel


from syftbox.lib.keycloak import create_user, get_admin_user, get_user_by_email, get_user_from_header, get_users, send_action_email, update_user

user_router = fastapi.APIRouter(
    prefix="/users",
    tags=["users"],
)

class RegisterResponse(BaseModel):
    bearer_token: str


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


@user_router.get("/check_user")
async def check_user(email: str) -> bool:
    user = get_user_by_email(email)
    if len(user) > 0:
        return True
    return False

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