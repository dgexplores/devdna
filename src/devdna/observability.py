import re
from dataclasses import dataclass, field
from uuid import uuid4

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id(value: str | None) -> str:
    if value is not None and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


def escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


@dataclass
class RequestMetrics:
    values: dict[tuple[str, str, int], tuple[int, float]] = field(default_factory=dict)

    def observe(self, method: str, route: str, status_code: int, duration: float) -> None:
        key = (method, route, status_code)
        count, total = self.values.get(key, (0, 0.0))
        self.values[key] = (count + 1, total + duration)

    def render(self) -> str:
        lines = [
            "# HELP devdna_http_requests_total Completed HTTP requests.",
            "# TYPE devdna_http_requests_total counter",
            "# HELP devdna_http_request_duration_seconds Request duration in seconds.",
            "# TYPE devdna_http_request_duration_seconds summary",
        ]
        for (method, route, status_code), (count, total) in sorted(self.values.items()):
            labels = (
                f'method="{escape_label(method)}",'
                f'route="{escape_label(route)}",'
                f'status="{status_code}"'
            )
            lines.append(f"devdna_http_requests_total{{{labels}}} {count}")
            lines.append(f"devdna_http_request_duration_seconds_count{{{labels}}} {count}")
            lines.append(f"devdna_http_request_duration_seconds_sum{{{labels}}} {total:.9f}")
        return "\n".join(lines) + "\n"
