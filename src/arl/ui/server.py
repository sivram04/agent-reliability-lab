"""`arl ui`: a local, read-only dashboard over result databases, and `--export` to a static folder."""

from __future__ import annotations

import json
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .data import Data

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2",
         ".txt": "text/plain; charset=utf-8"}


def _handler(data: Data):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200) -> None:
            self._send(status, json.dumps(obj, default=str).encode(), "application/json")

        def do_GET(self):  # noqa: N802
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in ("127.0.0.1", "localhost", "::1"):
                # A page on another site that rebinds its DNS to 127.0.0.1 must not read transcripts.
                return self._json({"error": "forbidden host"}, 403)
            url = urlparse(self.path)
            parts = [p for p in url.path.split("/") if p]
            try:
                if not parts or parts == ["index.html"]:
                    return self._send(200, (STATIC / "index.html").read_bytes(), TYPES[".html"])
                if parts[0] == "static" and len(parts) == 2:
                    path = (STATIC / parts[1]).resolve()
                    if path.parent != STATIC.resolve() or not path.is_file():
                        return self._json({"error": "not found"}, 404)
                    return self._send(200, path.read_bytes(), TYPES.get(path.suffix, "application/octet-stream"))
                if parts[0] != "api":
                    return self._json({"error": "not found"}, 404)
                if parts[1:] == ["runs"]:
                    return self._json(data.runs())
                if len(parts) == 3 and parts[1] == "runs":
                    return self._json(data.run(parts[2]))
                if len(parts) == 5 and parts[1] == "runs" and parts[3] == "replay":
                    return self._json(data.replay(parts[2], int(parts[4])))
                if parts[1:] == ["compare"]:
                    q = parse_qs(url.query)
                    return self._json(data.compare(q["base"][0], q["new"][0]))
                return self._json({"error": "not found"}, 404)
            except (KeyError, IndexError, StopIteration, ValueError) as exc:
                return self._json({"error": f"not found: {exc}"}, 404)
            except Exception as exc:  # noqa: BLE001  report, don't kill the server
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    return Handler


def serve(data: Data, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _handler(data))
    # Loading every scenario takes a few seconds; do it now so the first run page opens instantly.
    threading.Thread(target=data.scenario_index, daemon=True).start()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://{host}:{server.server_port}/")).start()
    return server


def export(data: Data, out: Path, per_target: int | None = 20, note: str | None = None,
           note_link: str | None = None) -> Path:
    """A self-contained read-only copy: opens from disk (file://) or any static host."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "static").mkdir(exist_ok=True)
    for f in STATIC.iterdir():
        if f.is_file() and f.name != "index.html":
            shutil.copy2(f, out / "static" / f.name)
    bundle = json.dumps(data.bundle(per_target), default=str).replace("</", "<\\/")
    (out / "static" / "data.js").write_text(f"window.ARL_DATA = {bundle};\n", encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace(
        '<script src="static/app.js"', '<script src="static/data.js"></script>\n<script src="static/app.js"')
    if note:  # a banner explaining what the snapshot is, e.g. for a public demo
        import html as _html
        link = (f' <a href="{_html.escape(note_link, quote=True)}">Learn more</a>'
                if note_link and note_link.startswith(("https://", "http://", "../", "/")) else "")
        html = html.replace("<body>", f'<body>\n<div class="export-note" role="note">{_html.escape(note)}{link}</div>', 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    return out / "index.html"
