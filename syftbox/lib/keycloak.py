import base64
import json
from functools import lru_cache
from typing import Annotated, List

import requests
from fastapi import Header, HTTPException

TOKEN_TIMEOUT = 3600

CLIENT_ID = "syftbox"
CLIENT_SECRET = "uyOaMdYsEtDfoNxKQ1jIT0CuP1EJa0J8"
ADMIN_UNAME = "info@openmined.org"
ADMIN_PASSWORD = "changethis"

KEYCLOAK_URL = "http://auth.syftbox.openmined.org"
KEYCLOAK_REALM = "master"


@lru_cache()
def get_token(username, password, ttl=None):
    del ttl
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": username,
        "password": password,
        "grant_type": "password",
    }

    resp = requests.post(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token", data=data)
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        return token
    else:
        raise Exception(f"Token request returned code {resp.status_code} with message {resp.text}")


def get_user_from_token(token):
    _, payload, _ = token.split(".")
    padded_payload = padded_payload = payload + "=" * divmod(len(payload), 4)[1]
    user_data = json.loads(base64.urlsafe_b64decode(padded_payload))
    return user_data


def get_user_info(token: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.post(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/userinfo", headers=headers)
    if resp.status_code != 200:
        return None
    content = resp.json()
    return content


def get_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def reset_password(user_id, new_password, token):
    data = {"type": "password", "temporary": False, "value": new_password}
    resp = requests.put(
        f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/users/{user_id}/reset-password", headers=get_headers(token), data=data
    )
    return resp


def create_keycloak_admin_token() -> str:
    return get_token(ADMIN_UNAME, ADMIN_PASSWORD)


def get_admin_headers():
    admin_token = create_keycloak_admin_token()
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def create_user(email, firstName, lastName, password):
    print(f"> {email}, {firstName}, {lastName}, {password}")
    userdata = {
        "firstName": firstName,
        "lastName": lastName,
        "email": email,
        "enabled": "true",
        "username": email,
        "credentials": [{"type": "password", "value": password, "temporary": False}],
    }
    return requests.post(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users", headers=get_admin_headers(), data=json.dumps(userdata)
    )


def send_action_email(user_id: str, actions: List[str]):
    return requests.put(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/execute-actions-email?client_id={CLIENT_ID}",
        headers=get_admin_headers(),
        data=json.dumps(actions),
    )


def get_users():
    resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/", headers=get_admin_headers())
    if resp.status_code == 200:
        content = resp.json()
        return content
    return resp.text


def get_user_from_header(token: Annotated[str, Header()]):
    user = get_user_info(token)
    if user is None or not user["enabled"]:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_admin_user(token: Annotated[str, Header()]):
    user = get_user_from_header(token)
    # check if the user is admin
    if user["email"] == ADMIN_UNAME:
        return user
    raise HTTPException(status_code=403, detail="User not admin")


def delete_user(user_id):
    resp = requests.delete(f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}", headers=get_admin_headers())
    if resp.status_code != 200:
        print(f"> error {resp.status_code} {resp.text}")
    return resp


def update_user(user_id, payload):
    return requests.get(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
        headers=get_admin_headers(),
        data=json.dumps(payload),
    )
