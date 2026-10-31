"""Routes for the application tracker page; daily/server.py hands requests here first.

  /applications              the page (tracker.html); /tracker redirects here
  /tracker/tracker.css, .js  the page's assets
  GET  /api/tracker          everything the page shows, joined from the CSV and the sidecar
  GET  /api/tracker/jd?id=   one saved job description as text
  POST /api/tracker/add      {"company": ..., "role": ..., ...}
  POST /api/tracker/update   {"id": ..., "changes": {...}}
  POST /api/tracker/followup {"id": ...} logs a sent follow-up
  POST /api/tracker/jd       {"id": ..., "text": ...} saves a job description that was missing

Any web page open in the browser can aim requests at localhost, so tracker requests must name
this server as their host and origin, and writes must be JSON (which forces a CORS preflight
this server never answers).
"""

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import tracker

HERE = Path(__file__).resolve().parent
ASSETS = {"tracker.html": "text/html; charset=utf-8", "tracker.css": "text/css; charset=utf-8",
          "tracker.js": "text/javascript; charset=utf-8"}
LOCAL = {"127.0.0.1", "localhost"}
MAX_BODY = 2_000_000


def _host(value: str) -> str:
    return re.sub(r":\d+$", "", (value or "").strip().lower())


def allowed(headers) -> bool:
    if _host(headers.get("Host", "")) not in LOCAL:
        return False
    origin = headers.get("Origin")
    return not origin or (urlsplit(origin).hostname or "") in LOCAL


def _json(handler, data, code=200):
    handler.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json", code)


def _guarded(handler, work):
    """Run a store call and turn its failures into something the page can show."""
    try:
        return _json(handler, work())
    except KeyError as exc:
        return _json(handler, {"error": str(exc.args[0]) if exc.args else "not found"}, 404)
    except tracker.Conflict as exc:
        return _json(handler, {"error": str(exc)}, 409)
    except ValueError as exc:
        return _json(handler, {"error": str(exc)}, 400)
    except OSError as exc:
        return _json(handler, {"error": f"Could not read or save the data: {exc}. "
                                        "If the CSV is open in Excel, close it and try again."}, 500)


def handle_get(handler) -> bool:
    url = urlsplit(handler.path)
    parts = [p for p in url.path.split("/") if p]
    if parts == ["tracker"]:
        handler.send_response(301)
        handler.send_header("Location", "/applications")
        handler.end_headers()
        return True
    if parts == ["applications"]:
        parts = ["tracker", "tracker.html"]
    if len(parts) == 2 and parts[0] == "tracker" and parts[1] in ASSETS:
        handler.send_bytes((HERE / parts[1]).read_bytes(), ASSETS[parts[1]])
        return True
    if parts[:2] != ["api", "tracker"]:
        return False
    if not allowed(handler.headers):
        handler.send_error(403)
    elif parts == ["api", "tracker"]:
        _guarded(handler, tracker.snapshot)
    elif parts == ["api", "tracker", "jd"]:
        app_id = parse_qs(url.query).get("id", [""])[0]
        _guarded(handler, lambda: {"text": tracker.get_posting(app_id)})
    else:
        handler.send_error(404)
    return True


def handle_post(handler) -> bool:
    if not handler.path.startswith("/api/tracker/"):
        return False
    json_body = handler.headers.get("Content-Type", "").split(";")[0].strip().lower() == "application/json"
    if not allowed(handler.headers) or not json_body:
        handler.send_error(403)
        return True
    try:
        size = int(handler.headers.get("Content-Length", 0))
        if size > MAX_BODY:
            raise ValueError("That is too large to save")
        body = json.loads(handler.rfile.read(size) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("bad request")
    except ValueError as exc:
        _json(handler, {"error": str(exc)}, 400)
        return True
    action = handler.path.rsplit("/", 1)[1]
    app_id = str(body.get("id", ""))
    if action == "add":
        _guarded(handler, lambda: tracker.add(body))
    elif action == "update":
        changes = body.get("changes")
        _guarded(handler, lambda: tracker.update(app_id, changes if isinstance(changes, dict) else {}))
    elif action == "followup":
        _guarded(handler, lambda: tracker.log_follow_up(app_id))
    elif action == "jd":
        _guarded(handler, lambda: tracker.add_posting(app_id, str(body.get("text", ""))))
    else:
        handler.send_error(404)
    return True
