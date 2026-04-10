import json
from datetime import UTC, datetime


def _json_response(start_response, payload, status="200 OK"):
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    start_response(status, headers)
    return [body]


def app(environ, start_response):
    """Minimal WSGI app for the Capitol Trades API workspace."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/":
        return _json_response(
            start_response,
            {
                "name": "Capitol Trades API",
                "status": "ok",
                "routes": ["/health"],
            },
        )

    if method == "GET" and path == "/health":
        return _json_response(
            start_response,
            {
                "status": "ok",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    return _json_response(
        start_response,
        {"error": "Not Found", "path": path},
        status="404 Not Found",
    )
