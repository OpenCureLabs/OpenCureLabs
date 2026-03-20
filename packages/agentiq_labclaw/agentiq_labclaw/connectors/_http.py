"""Shared HTTP session with exponential backoff and Retry-After support."""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("labclaw.connectors.http")

# Default retry strategy: 3 retries with exponential backoff on 429/500/502/503/504
_DEFAULT_RETRY = Retry(
    total=3,
    backoff_factor=1.0,          # 1s, 2s, 4s
    status_forcelist=[429, 500, 502, 503, 504],
    respect_retry_after_header=True,
    raise_on_status=False,
)


def resilient_session(
    timeout: int = 30,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
) -> requests.Session:
    """Create a requests.Session with automatic retry + backoff."""
    retry = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
