from datetime import UTC, datetime
import json
import subprocess

from app.routes import ROUTES
from app.utils.helpers import error_response, json_response

PYTHON_BIN = "/home/codespace/.python/current/bin/python"

_BOT_CONFIG = {
    "trading_bot": {
        "session": "trading_bot",
        "cwd": "/workspaces/Capitol_Trades_API/trading_bot",
        "cmd": f"PYTHON_BIN={PYTHON_BIN} bash ./supervise_bot.sh",
        "log": "/workspaces/Capitol_Trades_API/trading_bot/bot.log",
    },
    "crypto_bot": {
        "session": "crypto_bot",
        "cwd": "/workspaces/Capitol_Trades_API/crypto_bot",
        "cmd": f"PYTHON_BIN={PYTHON_BIN} bash ./supervise_bot.sh",
        "log": "/workspaces/Capitol_Trades_API/crypto_bot/bot.log",
    },
}


def _tmux_running(session):
    try:
        r = subprocess.run(["tmux", "has-session", "-t", session],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.returncode == 0
    except Exception:
        return False


def _last_log_lines(path, n=8):
    try:
        r = subprocess.run(["tail", f"-{n}", path],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.stdout.strip().splitlines()
    except Exception:
        return []


_FAULT_KEYWORDS = ("traceback (most recent call last)", "exception", "critical", "fatal")


def _get_faults(path):
    """Return lines from the log that look like errors/faults."""
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines if any(k in l.lower() for k in _FAULT_KEYWORDS)]
    except Exception:
        return []


def _clear_faults(path):
    """Truncate the bot log file to clear all recorded faults."""
    try:
        open(path, "w").close()
        return True
    except Exception:
        return False


def _check_bot_status():
    trading_running = _tmux_running("trading_bot")
    crypto_running = _tmux_running("crypto_bot")
    t_faults = _get_faults(_BOT_CONFIG["trading_bot"]["log"])
    c_faults = _get_faults(_BOT_CONFIG["crypto_bot"]["log"])
    return {
        "trading_bot": {
            "running": trading_running,
            "session": "trading_bot",
            "log": _last_log_lines(_BOT_CONFIG["trading_bot"]["log"]),
            "faults": t_faults[-20:],
            "fault_count": len(t_faults),
        },
        "crypto_bot": {
            "running": crypto_running,
            "session": "crypto_bot",
            "log": _last_log_lines(_BOT_CONFIG["crypto_bot"]["log"]),
            "faults": c_faults[-20:],
            "fault_count": len(c_faults),
        },
        "all_running": trading_running and crypto_running,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _bot_control(bot_id, action):
    cfg = _BOT_CONFIG.get(bot_id)
    if not cfg:
        return False, f"Unknown bot: {bot_id}"
    session = cfg["session"]
    if action == "start":
        if _tmux_running(session):
            return True, f"{bot_id} is already running."
        try:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", session,
                 f"cd {cfg['cwd']} && {cfg['cmd']}"],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return True, f"{bot_id} started."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to start {bot_id}: {e.stderr.decode().strip()}"
    elif action == "stop":
        if not _tmux_running(session):
            return True, f"{bot_id} is not running."
        try:
            subprocess.run(["tmux", "kill-session", "-t", session],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True, f"{bot_id} stopped."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to stop {bot_id}: {e.stderr.decode().strip()}"
    elif action == "clear_faults":
        ok = _clear_faults(cfg["log"])
        return ok, f"Faults cleared for {bot_id}." if ok else f"Could not clear faults for {bot_id}."
    return False, f"Unknown action: {action}"


def app(environ, start_response):
    """WSGI application for the Capitol Trades API workspace."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/bot_status":
        return json_response(start_response, _check_bot_status())

    if method == "POST" and path == "/bot_control":
        try:
            length = int(environ.get("CONTENT_LENGTH", 0) or 0)
            body = environ["wsgi.input"].read(length)
            params = json.loads(body) if body else {}
        except Exception:
            params = {}
        ok, message = _bot_control(params.get("bot", ""), params.get("action", ""))
        status_code = "200 OK" if ok else "400 Bad Request"
        start_response(status_code, [("Content-Type", "application/json"),
                                     ("Access-Control-Allow-Origin", "*")])
        return [json.dumps({"ok": ok, "message": message}).encode()]

    if method == "GET" and path == "/bot_status_page":
        try:
            with open("app/bot_status.html", "rb") as f:
                html = f.read()
            start_response("200 OK", [("Content-Type", "text/html")])
            return [html]
        except Exception as exc:
            return error_response(start_response, f"Could not load status page: {exc}",
                                  status="500 Internal Server Error")

    if method == "GET" and path == "/":
        return json_response(start_response, {
            "name": "Capitol Trades API",
            "status": "ok",
            "routes": ["/health", "/trades", "/politicians", "/sectors", "/news",
                       "/bot_status", "/bot_status_page", "/bot_control"],
        })

    if method == "GET" and path == "/health":
        return json_response(start_response, {
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
        })

    handler = ROUTES.get((method, path))
    if handler is None:
        return error_response(start_response, "Not Found", status="404 Not Found",
                              details={"path": path})
    try:
        return json_response(start_response, handler(environ))
    except ValueError as exc:
        return error_response(start_response, str(exc), status="400 Bad Request")
    except Exception as exc:
        return error_response(start_response, "Unable to fetch Capitol Trades data right now.",
                              status="502 Bad Gateway", details={"message": str(exc)})

