from datetime import UTC, datetime

from app.routes import ROUTES
from app.utils.helpers import error_response, json_response


def app(environ, start_response):
    """WSGI application for the Capitol Trades API workspace."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/":
        return json_response(
            start_response,
            {
                "name": "Capitol Trades API",
                "status": "ok",
                "routes": ["/health", "/trades", "/politicians", "/sectors", "/news"],
            },
        )

    if method == "GET" and path == "/health":
        return json_response(
            start_response,
            {
                "status": "ok",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    handler = ROUTES.get((method, path))
    if handler is None:
        return error_response(
            start_response,
            "Not Found",
            status="404 Not Found",
            details={"path": path},
        )

    try:
        return json_response(start_response, handler(environ))
    except ValueError as exc:
        return error_response(start_response, str(exc), status="400 Bad Request")
    except Exception as exc:
        return error_response(
            start_response,
            "Unable to fetch Capitol Trades data right now.",
            status="502 Bad Gateway",
            details={"message": str(exc)},
        )
