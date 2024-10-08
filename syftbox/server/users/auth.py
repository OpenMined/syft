import secrets
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

ADMIN_USERNAME = "info@openmined.org"
ADMIN_PASSWORD = "changethis"


def verify_admin_credentials(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
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
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
