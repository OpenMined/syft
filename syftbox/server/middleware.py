import time

from fastapi import Request
from loguru import logger
from opentelemetry.trace import get_current_span
from starlette.middleware.base import BaseHTTPMiddleware


class LoguruMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.2f}s")

        return response


class EmailTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Get email from request headers or state
        email = request.headers.get("email")
        if email is None:
            email = "anonymous"

        # Add email to current span
        current_span = get_current_span()
        current_span.set_attribute("client.email", email)

        response = await call_next(request)
        return response
