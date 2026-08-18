"""Public API for PhantomCurl."""

from phantom_curl.client import PhantomClient
from phantom_curl.exceptions import (
    ConnectionRejectedError,
    DOMBuildError,
    HTTPError,
    JSRuntimeError,
    PhantomError,
    RequestTimeoutError,
    StaleElementError,
)
from phantom_curl.models import (
    Cookie,
    OriginPolicy,
    ProxyConfig,
    RequestOptions,
    Response,
    RetryConfig,
    StealthConfig,
    StorageState,
)
from phantom_curl.page import Page
from phantom_curl.element import Element

__all__ = [
    "PhantomClient",
    "Page",
    "Cookie",
    "OriginPolicy",
    "ProxyConfig",
    "RequestOptions",
    "Response",
    "Element",
    "RetryConfig",
    "StealthConfig",
    "StorageState",
    "PhantomError",
    "ConnectionRejectedError",
    "DOMBuildError",
    "HTTPError",
    "JSRuntimeError",
    "RequestTimeoutError",
    "StaleElementError",
]
