"""HTTP span tag helpers that write either the Datadog or the OTel attribute, depending on the active semantics."""

from typing import Any
from typing import Optional
from typing import Union
from typing import cast

from ddtrace._trace.otel.http.tags import _obfuscated_query
from ddtrace._trace.otel.http.tags import _sanitized_url
from ddtrace._trace.otel.http.tags import _set_otel_query
from ddtrace._trace.otel.http.tags import is_otel_server_error_status
from ddtrace._trace.otel.http.tags import normalize_http_method
from ddtrace._trace.otel.http.tags import set_url_tags_otel_server
from ddtrace._trace.span import Span
from ddtrace.ext import http
from ddtrace.ext import net
from ddtrace.internal.logger import get_logger
from ddtrace.internal.otel_semantics import http as otel_http
from ddtrace.internal.settings._config import config
from ddtrace.internal.settings.integration import IntegrationConfig


log = get_logger(__name__)


def set_client_address_tags(
    span: Span, client_address: Optional[str], network_peer_address: Optional[str] = None
) -> None:
    if config._otel_trace_semantics_enabled:
        if client_address:
            span._set_attribute(otel_http.CLIENT_ADDRESS, client_address)
        if network_peer_address:
            span._set_attribute(otel_http.NETWORK_PEER_ADDRESS, network_peer_address)
    else:
        if client_address:
            span._set_attribute(http.CLIENT_IP, client_address)
        if network_peer_address:
            span._set_attribute(net.CLIENT_IP, network_peer_address)


def set_query_string_tag(span: Span, query: str) -> None:
    if config._otel_trace_semantics_enabled:
        _set_otel_query(span, query)
    else:
        span._set_attribute(http.QUERY_STRING, query)


def is_otel_non_error_status(status_code: int) -> bool:
    return config._otel_trace_semantics_enabled and not is_otel_server_error_status(status_code)


def copy_server_url_tags(source: Span, destination: Span) -> None:
    if not config._otel_trace_semantics_enabled:
        destination.set_tag(http.URL, source.get_tag(http.URL))
        return

    for key in (
        otel_http.URL_SCHEME,
        otel_http.URL_PATH,
        otel_http.URL_QUERY,
        net.SERVER_ADDRESS,
        otel_http.SERVER_PORT,
    ):
        value = source._get_attribute(key)
        if value is not None:
            destination._set_attribute(key, value)


def http_block_metadata(
    method: Optional[str],
    status_code: Union[int, str],
    query: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if not config._otel_trace_semantics_enabled:
        metadata[http.STATUS_CODE] = str(status_code)
        if method is not None:
            metadata[http.METHOD] = method
        if query:
            metadata[http.QUERY_STRING] = query
        if user_agent:
            metadata[http.USER_AGENT] = user_agent
        return metadata

    metadata[otel_http.RESPONSE_STATUS_CODE] = int(status_code)
    if method is not None:
        normalized_method, original_method = normalize_http_method(method)
        metadata[otel_http.REQUEST_METHOD] = normalized_method
        if original_method is not None:
            metadata[otel_http.REQUEST_METHOD_ORIGINAL] = original_method
    if query:
        obfuscated = _obfuscated_query(query)
        if obfuscated:
            metadata[otel_http.URL_QUERY] = cast(Any, obfuscated)
    if user_agent:
        metadata[otel_http.USER_AGENT_ORIGINAL] = user_agent
    return metadata


def set_url_tags_server(
    integration_config: IntegrationConfig, span: Span, url: str, query: Optional[str], raw_uri: Optional[str] = None
) -> None:
    if config._otel_trace_semantics_enabled:
        set_url_tags_otel_server(integration_config, span, url, query, raw_uri)
    else:
        span._set_attribute(
            http.URL,
            cast(Any, _sanitized_url(url, query, integration_config.http_tag_query_string)),
        )


def set_status_code_tag(span: Span, status_code: Union[int, str]) -> None:
    if not config._otel_trace_semantics_enabled:
        span._set_attribute(http.STATUS_CODE, str(status_code))
        return
    try:
        int_status_code = int(status_code)
    except (TypeError, ValueError):
        log.debug("failed to convert http status code %r to int", status_code)
        return
    span._set_attribute(otel_http.RESPONSE_STATUS_CODE, int_status_code)
