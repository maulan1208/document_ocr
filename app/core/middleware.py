import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request

from app.core.logging_config import bind_request_id, reset_request_id

logger = logging.getLogger(__name__)


async def request_logging_middleware(request: Request, call_next):
    request_id = uuid4().hex
    request_id_token = bind_request_id(request_id)
    started_at = perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "api_request_failed method=%s path=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            (perf_counter() - started_at) * 1000,
        )
        raise
    else:
        response.headers["X-Request-ID"] = request_id
        log_method = logger.error if response.status_code >= 500 else logger.info
        log_method(
            "api_request_completed method=%s path=%s status_code=%d "
            "duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            (perf_counter() - started_at) * 1000,
        )
        return response
    finally:
        reset_request_id(request_id_token)
