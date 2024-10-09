from datetime import datetime, timedelta, timezone
import secrets
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer

from syftbox.server.settings import ServerSettings, get_server_settings
from syftbox.server.users.router import get_user_manager
from syftbox.server.users.user import User, UserManager
import jwt

JWT_ALGORITHM = "HS256"
http_basic_security = HTTPBasic()  # Used for admin credentials
bearer_scheme = HTTPBearer()  # Used for User JWT tokens


def create_access_token(user: User, settings: ServerSettings) -> str:
    """Create JWT token for user, without expiry date.

    Args:
        user (User): user to issue token for
        settings (ServerSettings): server settings, including JWT secret

    Returns:
        str: JWT token
    """
    payload = {"sub": user.email}
    encoded_jwt = jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
    settings: Annotated[ServerSettings, Depends(get_server_settings)],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except jwt.InvalidTokenError:
        raise credentials_exception

    user = user_manager.get_user(email)
    if user is None:
        raise credentials_exception

    return user


def verify_admin_credentials(
    credentials: Annotated[HTTPBasicCredentials, Depends(http_basic_security)],
    settings: Annotated[ServerSettings, Depends(get_server_settings)],
) -> Literal[True]:
    """
    HTTPBasic authentication that checks if the admin credentials are correct.

    Args:
        credentials (Annotated[HTTPBasicCredentials, Depends): HTTPBasic credentials

    Raises:
        HTTPException: 401 Unauthorized if the credentials are incorrect

    Returns:
        bool: True if the credentials are correct
    """
    admin_username = settings.admin_username
    admin_password = settings.admin_password

    correct_username = secrets.compare_digest(credentials.username, admin_username)
    correct_password = secrets.compare_digest(credentials.password, admin_password)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
