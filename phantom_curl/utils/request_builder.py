from __future__ import annotations

from typing import Any, Mapping, Optional, Union

from phantom_curl.models import ProxyConfig, RequestOptions, RetryConfig


ProxyInput = Union[ProxyConfig, str]


def _to_proxy_config(proxy: ProxyInput) -> ProxyConfig:
    """Normalize a public proxy value into the internal immutable model."""
    return ProxyConfig.from_string(proxy) if isinstance(proxy, str) else proxy


def build_request_options(
    method: str,
    url: str,
    headers: Optional[Mapping[str, str]] = None,
    params: Optional[Mapping[str, Any]] = None,
    cookies: Optional[Mapping[str, str]] = None,
    data: Optional[Any] = None,
    json: Optional[Any] = None,
    timeout: float = 30.0,
    allow_redirects: bool = True,
    verify: bool = True,
    proxy: Optional[ProxyInput] = None,
    proxies: Optional[Mapping[str, ProxyInput]] = None,
    retry_config: Optional[RetryConfig] = None,
) -> RequestOptions:
    """
    Internal helper to build RequestOptions from the provided parameters.
    """
    normalized_proxy = _to_proxy_config(proxy) if proxy is not None else None
    normalized_proxies = (
        {protocol: _to_proxy_config(value) for protocol, value in proxies.items()} if proxies is not None else None
    )

    return RequestOptions(
        method=method,
        url=url,
        headers=headers or {},
        params=params or {},
        cookies=cookies or {},
        data=data,
        json_body=json,
        timeout=timeout,
        allow_redirects=allow_redirects,
        verify=verify,
        proxy=normalized_proxy,
        proxies=normalized_proxies,
        retry_config=retry_config,
    )
