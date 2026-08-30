import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_PARTS = ("authorization", "cookie", "password", "secret", "token", "api_key")


def redact_sensitive_values(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in tuple(event_dict):
        normalized = str(key).lower().replace("-", "_")
        if any(part in normalized for part in SENSITIVE_PARTS):
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(environment: str) -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive_values,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if environment == "production"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
