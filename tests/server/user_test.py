import secrets

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
from fastapi.testclient import TestClient

from syftbox.server.server import app as server_app
from syftbox.server.users.auth import ADMIN_PASSWORD, ADMIN_USERNAME, verify_admin_credentials
from syftbox.server.users.user import User, UserManager


@pytest.fixture(scope="function")
def client():
    with TestClient(server_app) as client:
        yield client


@pytest.fixture(scope="function")
def user_with_token(client) -> User:
    user_manager: UserManager = client.app_state["user_manager"]
    return user_manager.create_token_for_user("user@openmined.org")


@pytest.fixture(scope="function")
def registered_user(client, user_with_token) -> User:
    user_manager: UserManager = client.app_state["user_manager"]
    user = user_manager.register_user(user_with_token.email, user_with_token.token)
    return user


@pytest.fixture(scope="function")
def admin_credentials() -> HTTPBasicCredentials:
    return HTTPBasicCredentials(username=ADMIN_USERNAME, password=ADMIN_PASSWORD)


def test_verify_admin_credentials(client, admin_credentials):
    assert verify_admin_credentials(admin_credentials)

    wrong_email = HTTPBasicCredentials(username="wrong", password=ADMIN_PASSWORD)
    with pytest.raises(HTTPException):
        verify_admin_credentials(wrong_email)

    wrong_password = HTTPBasicCredentials(username=ADMIN_USERNAME, password="wrong")
    with pytest.raises(HTTPException):
        verify_admin_credentials(wrong_password)

    # Test when it is used as a dependency
    result = client.post(
        "/users/register_tokens",
        json=["test_user@openmined.org"],
        auth=(admin_credentials.username, admin_credentials.password),
    )
    assert result.status_code == 200, result.json()
    print(result.json())

    # wrong admin credentials fails
    result = client.post(
        "/users/register_tokens",
        json=["test_user@openmined.org"],
        auth=(wrong_password.username, wrong_password.password),
    )
    assert result.status_code == 401, result.json()
    print(result.json())

    # no credentials fails
    result = client.post(
        "/users/register_tokens",
        json=["test_user@openmined.org"],
    )
    assert result.status_code == 401, result.json()
    print(result.json())


def test_register_tokens(client, admin_credentials):
    user_manager: UserManager = client.app_state["user_manager"]

    num_users = 3
    emails = [f"user_{i}@openmined.org" for i in range(num_users)]

    result = client.post(
        "/users/register_tokens",
        json=emails,
        auth=(admin_credentials.username, admin_credentials.password),
    )
    result.raise_for_status()
    content = result.json()
    assert len(content) == num_users

    # all users exist
    for email in emails:
        user = user_manager.get_user(email)
        assert user is not None
        assert user.email == email
        assert not user.is_banned and not user.is_registered  # not banned, not registered


def test_update_nonexisting_user(client, admin_credentials):
    result = client.post(
        "/users/update",
        params={"email": "doesnt_exist@openmined.org"},
        json={"is_banned": True},
        auth=(admin_credentials.username, admin_credentials.password),
    )
    assert result.status_code == 404, result.json()


def test_update_user(client, admin_credentials, registered_user):
    user_manager: UserManager = client.app_state["user_manager"]
    assert not registered_user.is_banned
    assert registered_user.is_registered

    # auth is required
    result = client.post(
        "/users/update",
        params={"email": registered_user.email},
        json={"is_banned": True},
    )
    assert result.status_code == 401, result.json()

    result = client.post(
        "/users/update",
        params={"email": registered_user.email},
        json={"is_banned": True, "is_registered": False},
        auth=(admin_credentials.username, admin_credentials.password),
    )
    result.raise_for_status()
    user = user_manager.get_user(registered_user.email)
    assert user.is_banned
    assert not user.is_registered


def test_register_user(client, user_with_token):
    user_manager: UserManager = client.app_state["user_manager"]
    assert user_manager.get_user(user_with_token.email).is_registered is False

    # wrong token
    wrong_token = secrets.token_urlsafe(32)
    result = client.post(
        "/users/register",
        params={"email": user_with_token.email, "token": wrong_token},
    )
    assert result.status_code == 404, result.json()
    assert user_manager.get_user(user_with_token.email).is_registered is False

    # correct token
    result = client.post(
        "/users/register",
        params={"email": user_with_token.email, "token": user_with_token.token},
    )
    result.raise_for_status()
    assert user_manager.get_user(user_with_token.email).is_registered
