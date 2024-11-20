import base64
from datetime import datetime, timezone
import json
from typing_extensions import Annotated
from fastapi import Depends, HTTPException, Header, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
import jwt
from syftbox.server.settings import ServerSettings, get_server_settings

bearer_scheme = HTTPBearer()

ACCESS_TOKEN = "access_token"
EMAIL_TOKEN = "email_token"


def _validate_jwt(server_settings: ServerSettings, token: str) -> dict:
    try:
        return jwt.decode(
            token,
            server_settings.jwt_secret.get_secret_value(),
            algorithms=[server_settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

def _generate_jwt(server_settings: ServerSettings, data: dict) -> str:
    return jwt.encode(
        data,
        server_settings.jwt_secret.get_secret_value(),
        algorithm=server_settings.jwt_algorithm,
    )


def _generate_base64(server_settings: ServerSettings, data: dict) -> str:
    try:
        payload = {}
        for k, v in data.items():
            if isinstance(v, datetime):
                payload[k] = v.isoformat()
            else:
                payload[k] = v
        return base64.b64encode(json.dumps(payload).encode()).decode()
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail="Error encoding token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _validate_base64(server_settings: ServerSettings, token: str) -> dict:
    try:
        payload = json.loads(base64.b64decode(token).decode())
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail="Invalid base64 token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if "exp" in payload and datetime.fromisoformat(payload["exp"]) < datetime.now(tz=timezone.utc):
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload



def generate_token(server_settings: ServerSettings, data: json) -> str:
    """
    payload looks like:
    {email: x, iat: date, type: access_token, exp: date}

    If no auth, the token is a base64 encoded json string.
    If auth, the token is a jwt token.

    Args:
        server_settings (ServerSettings): server settings
        data (json): data to encode

    Returns:
        str: encoded token
    """
    if not server_settings.auth_enabled:
        return _generate_base64(server_settings, data)
    else:
        return _generate_jwt(server_settings, data)

def validate_token(server_settings: ServerSettings, token: str) -> dict:
    """
    payload looks like:
    {email: x, iat: date, type: access_token, exp: date}

    If no auth, the token is a base64 encoded json string.
    If auth, the token is a jwt token.

    Args:
        server_settings (ServerSettings): server settings
        token (str): token to decode

    Returns:
        dict: decoded payload
    """
    if not server_settings.auth_enabled:
        return _validate_base64(server_settings, token)
    else:
        return _validate_jwt(server_settings, token)


def generate_access_token(server_settings: ServerSettings, email: str) -> str:
    data = {
        "email": email,
        "type": ACCESS_TOKEN,
        "iat": datetime.now(tz=timezone.utc),
    }
    if server_settings.jwt_access_token_exp:
        data["exp"] = data["iat"] + server_settings.jwt_access_token_exp
    return generate_token(server_settings, data)


def generate_email_token(server_settings: ServerSettings, email: str) -> str:
    data = {
        "email": email,
        "type": EMAIL_TOKEN,
        "iat": datetime.now(tz=timezone.utc),
    }
    if server_settings.jwt_email_token_exp:
        data["exp"] = data["iat"] + server_settings.jwt_email_token_exp
    return generate_token(server_settings, data)


def validate_access_token(server_settings: ServerSettings, token: str) -> dict:
    data = validate_token(server_settings, token)
    if data["type"] != ACCESS_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return data


def validate_email_token(server_settings: ServerSettings, token: str) -> dict:
    data = validate_token(server_settings, token)
    if data["type"] != EMAIL_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return data


def get_user_from_email_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
    server_settings: Annotated[ServerSettings, Depends(get_server_settings)],
) -> str:
    payload = validate_email_token(server_settings, credentials.credentials)
    return payload["email"]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
    server_settings: Annotated[ServerSettings, Depends(get_server_settings)],
) -> str:
    payload = validate_access_token(server_settings, credentials.credentials)
    return payload["email"]