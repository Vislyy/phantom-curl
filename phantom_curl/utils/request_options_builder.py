from __future__ import annotations

from typing import Optional, Mapping, Any

from phantom_curl.models import ProxyConfig, RequestOptions

def build_request_options(
    method: str,
    url: str,
    headers: Optional[Mapping[str, str]] = None,
    params: Optional[Mapping[str, Any]] = None,
    cookies: Optional[Mapping[str, str]] = None,
    data: Optional[Any] = None,
    json: Optional[Any] = None,
    timeout: Optional[float] = 30.0,
    allow_redirects: bool = True,
    verify: bool = True,
    proxy: Optional[ProxyConfig] = None,
    proxies: Optional[Mapping[str, ProxyConfig]] = None
) -> RequestOptions:
    """
    Internal helper to build RequestOptions from the provided parameters.
    """
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
        proxy=proxy,
        proxies=proxies,
    )