import logging
import sys
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog
from structlog.types import EventDict, Processor


def drop_extra_keys(_, __, event_dict: EventDict) -> EventDict:
    # Uvicorn adds a color version of its messages, but we don't want it.
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging(log_level="INFO"):
    # If we're on a console (aka local dev), output easily readable logs, not JSON
    json_logs = not sys.stderr.isatty()

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        drop_extra_keys,
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        # Format the exception only for JSON logs, as we want to pretty-print them when
        # using the ConsoleRenderer
        shared_processors.append(structlog.processors.format_exc_info)
        # Use ISO format for timestamps in JSON logs
        shared_processors.append(structlog.processors.TimeStamper(fmt="iso"))
    else:
        # Use a human-readable timestamp format for console logs
        shared_processors.append(
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False)
        )

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    log_renderer: structlog.types.Processor
    if json_logs:
        log_renderer = structlog.processors.JSONRenderer()
    else:
        log_renderer = structlog.dev.ConsoleRenderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        # These run ONLY on `logging` entries that do NOT originate within
        # structlog.
        foreign_pre_chain=shared_processors,
        # These run on ALL entries after the pre_chain is done.
        processors=[
            # Remove _record & _from_structlog.
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            log_renderer,
        ],
    )

    # Reconfigure the root logger to use our structlog formatter, effectively emitting the logs via structlog
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    for h in root_logger.handlers:
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    for uvicorn_log in ["uvicorn", "uvicorn.error"]:
        # Make sure the logs are handled by the root logger
        logging.getLogger(uvicorn_log).handlers.clear()
        logging.getLogger(uvicorn_log).propagate = True

    # Uvicorn logs are re-emitted with more context. We effectively silence them here
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False


def structlog_context_middleware_factory(logger_name):
    """
    This factory creates a FastAPI middleware that provides context logging
    and can be used across different Uvicorn instances. The logger_name parameter
    provides a way to identify which Uvicorn instance a log entry came from.
    """

    class StructlogContextMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Clear previous context variables
            structlog.contextvars.clear_contextvars()

            # Generate a request ID and bind it to the general context
            request_id = str(uuid.uuid4())
            structlog.contextvars.bind_contextvars(request_id=request_id)

            # Create a separate logger for access logs
            access_log = structlog.get_logger(logger_name)

            # Make the request and receive a response
            response = await call_next(request)

            # Log the response details using the access logger
            access_log.info(
                "http:request_complete",
                status_code=response.status_code,
                method=request.method,
                path=request.url.path,
                client_host=request.client.host,
                client_port=request.client.port,
            )

            return response

    return StructlogContextMiddleware
