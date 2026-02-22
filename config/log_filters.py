"""
Logging filters to prevent PII and sensitive data from leaking into log output.

Automatically scrubs email addresses, Australian TFNs, and phone numbers.
Applied via the LOGGING configuration in settings.py.
"""
import logging
import re


class SensitiveDataFilter(logging.Filter):
    """Redact PII patterns (emails, TFNs, phone numbers) from log records."""

    PATTERNS = [
        # Email addresses
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
        # Australian TFN: 9 digits, optionally separated by spaces or hyphens
        (re.compile(r"\b\d{3}[\s-]?\d{3}[\s-]?\d{3}\b"), "[TFN]"),
        # Australian phone: 04xx xxx xxx, +61 x xxxx xxxx, or (0x) xxxx xxxx
        (re.compile(r"(?:\+61|0)\d[\s.-]?\d{4}[\s.-]?\d{4}"), "[PHONE]"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._scrub(a) for a in record.args)
        return True

    def _scrub(self, value):
        if not isinstance(value, str):
            return value
        for pattern, replacement in self.PATTERNS:
            value = pattern.sub(replacement, value)
        return value
