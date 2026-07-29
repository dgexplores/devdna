import json
import logging

from devdna.logging import JsonFormatter
from devdna.observability import RequestMetrics, request_id


def test_metrics_render_bounded_request_labels() -> None:
    metrics = RequestMetrics()
    metrics.observe("GET", "/v1/analyses/{analysis_id}", 200, 0.125)
    metrics.observe("GET", "/v1/analyses/{analysis_id}", 200, 0.075)

    rendered = metrics.render()

    assert (
        'devdna_http_requests_total{method="GET",route="/v1/analyses/{analysis_id}",status="200"} 2'
    ) in rendered
    assert (
        'devdna_http_request_duration_seconds_sum{method="GET",'
        'route="/v1/analyses/{analysis_id}",status="200"} 0.200000000'
    ) in rendered


def test_request_id_accepts_safe_values_and_replaces_unsafe_values() -> None:
    assert request_id("trace-123") == "trace-123"
    assert request_id("unsafe\nvalue") != "unsafe\nvalue"
    assert request_id(None)


def test_json_formatter_includes_request_context() -> None:
    record = logging.LogRecord(
        "devdna",
        logging.INFO,
        __file__,
        1,
        "request complete",
        (),
        None,
    )
    record.request_id = "trace-123"
    record.status_code = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["request_id"] == "trace-123"
    assert payload["status_code"] == 200
