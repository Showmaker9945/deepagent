from __future__ import annotations

import logging

LOG_CONTEXT_FIELDS = ("run_id", "category", "status", "tool_name", "duration_ms", "event_type")


class StructuredLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        context_parts: list[str] = []
        for field in LOG_CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is None or value == "":
                continue
            context_parts.append(f"{field}={value}")
        if context_parts:
            return f"{message} {' '.join(context_parts)}"
        return message


def configure_logging(level_name: str = "INFO") -> None:
    root_logger = logging.getLogger()
    level = getattr(logging, level_name.upper(), logging.INFO)

    if getattr(configure_logging, "_configured", False):
        root_logger.setLevel(level)
        return

    logging.captureWarnings(True)
    handler = logging.StreamHandler()
    handler.setFormatter(
        StructuredLogFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    configure_logging._configured = True
