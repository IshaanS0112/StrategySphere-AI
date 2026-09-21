"""SEC EDGAR access.

This package is the only one in the project permitted to make outbound network
calls other than the LLM client, and it only ever talks to data.sec.gov. It
writes a benchmark table to disk; the SWOT engine keeps reading a table from a
path and never learns that HTTP exists.
"""

from app.services.edgar.client import (
    EdgarClient,
    EdgarConfigError,
    EdgarFetchError,
    EdgarOfflineError,
    client_from_settings,
    validate_user_agent,
)

__all__ = [
    "EdgarClient",
    "EdgarConfigError",
    "EdgarFetchError",
    "EdgarOfflineError",
    "client_from_settings",
    "validate_user_agent",
]
