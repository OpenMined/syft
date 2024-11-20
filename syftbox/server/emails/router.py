import httpx
from fastapi import APIRouter, Depends
from loguru import logger

from syftbox.server.emails.models import BatchSendEmailRequest, SendEmailRequest
from syftbox.server.settings import ServerSettings, get_server_settings

from .constants import EMAIL_SERVICE_API_URL

router = APIRouter(prefix="/emails", tags=["email"])

# TODO add some safety mechanisms to the below endpoints (rate limiting, authorization, etc)


@router.post("/")
async def send_email(
    email_request: SendEmailRequest,
    server_settings: ServerSettings = Depends(get_server_settings),
) -> bool:
    if not server_settings.email_service_api_key:
        raise httpx.HTTPStatusError("Email service API key is not set", request=None, response=None)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            EMAIL_SERVICE_API_URL,
            headers={
                "Authorization": f"Bearer {server_settings.email_service_api_key}",
                "Content-Type": "application/json",
            },
            json=email_request.json_for_request(),
        )
        if response.status_code == 200:
            sent_to = email_request.to if isinstance(email_request.to, str) else ", ".join(email_request.to)
            logger.info(f"Email sent successfully to {sent_to}")
            return True
        else:
            logger.error(f"Failed to send email: {response.text}")
            return False


@router.post("/batch")
async def send_batch_email(
    email_requests: BatchSendEmailRequest,
    server_settings: ServerSettings = Depends(get_server_settings),
) -> bool:
    """Trigger up to 100 batch emails at once.

    Instead of sending one email per HTTP request, we provide a batching endpoint that
    permits you to send up to 100 emails in a single API call.
    """
    if not server_settings.email_service_api_key:
        raise httpx.HTTPStatusError("Email service API key is not set", request=None, response=None)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMAIL_SERVICE_API_URL}/batch",
            headers={
                "Authorization": f"Bearer {server_settings.email_service_api_key}",
                "Content-Type": "application/json",
            },
            json=email_requests.json_for_request(),
        )
        if response.status_code == 200:
            logger.info(f"{len(email_requests)} emails sent successfully")
            return True
        else:
            logger.error(f"Failed to send email: {response.text}")
            return False
