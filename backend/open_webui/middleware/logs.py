import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog


class StructlogContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Clear previous context variables
        structlog.contextvars.clear_contextvars()

        # Generate a request ID and bind it to the general context
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Create a separate logger for access logs
        access_log = structlog.get_logger("http.access")

        # Make the request and receive a response
        response = await call_next(request)

        # Log the response details using the access logger
        access_log.info(
            "Request completed",
            status_code=response.status_code,
            method=request.method,
            path=request.url.path,
            client_host=request.client.host,
            client_port=request.client.port,
        )

        return response
