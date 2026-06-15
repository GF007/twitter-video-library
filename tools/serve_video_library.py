import argparse
import email.utils
import json
import os
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_EDITS = {
    "schema_version": 1,
    "updated_at": None,
    "excluded": {},
    "category_overrides": {},
}

CANONICAL_CATEGORIES = {
    "动画分镜": "动画分镜",
    "分镜": "动画分镜",
    "storyboard": "动画分镜",
    "animatic": "动画分镜",
    "layout": "动画分镜",
    "动画片段": "动画片段",
    "动画": "动画片段",
    "clip": "动画片段",
    "animation": "动画片段",
    "其他": "其他",
    "other": "其他",
    "unclear": "其他",
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def normalize_category(value):
    text = str(value or "").strip()
    if not text:
        return "其他"
    return CANONICAL_CATEGORIES.get(text.lower(), text)


def default_edits():
    return json.loads(json.dumps(DEFAULT_EDITS))


def normalize_edits(data):
    if not isinstance(data, dict):
        data = {}
    edits = default_edits()
    edits["updated_at"] = data.get("updated_at")
    excluded = data.get("excluded")
    overrides = data.get("category_overrides")
    if isinstance(excluded, dict):
        edits["excluded"] = excluded
    if isinstance(overrides, dict):
        edits["category_overrides"] = overrides
    return edits


def read_json(path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return json.load(handle)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp_path, path)


def load_edits(path):
    return normalize_edits(read_json(path, default=default_edits()))


class RangeReader:
    def __init__(self, handle, remaining):
        self.handle = handle
        self.remaining = remaining

    def read(self, size=-1):
        if self.remaining <= 0:
            return b""
        if size is None or size < 0 or size > self.remaining:
            size = self.remaining
        data = self.handle.read(size)
        self.remaining -= len(data)
        return data

    def close(self):
        self.handle.close()


def make_handler(project_root):
    manual_path = project_root / "library" / "manual-edits.json"

    class VideoLibraryHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(project_root), **kwargs)

        def log_message(self, format, *args):
            print(f"{self.address_string()} - {format % args}")

        def send_json(self, status, payload):
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def read_body_json(self):
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            if length > 1024 * 1024:
                raise ValueError("request body too large")
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def ensure_edits(self):
            edits = load_edits(manual_path)
            if not manual_path.exists():
                write_json(manual_path, edits)
            return edits

        def parse_range(self, value, total_size):
            unit, separator, spec = value.partition("=")
            if separator != "=" or unit.strip().lower() != "bytes":
                raise ValueError("unsupported range unit")

            spec = spec.strip()
            if not spec or "," in spec:
                raise ValueError("unsupported range set")

            start_text, separator, end_text = spec.partition("-")
            if separator != "-":
                raise ValueError("invalid byte range")

            start_text = start_text.strip()
            end_text = end_text.strip()

            if not start_text:
                if not end_text.isdigit():
                    raise ValueError("invalid suffix range")
                suffix_length = int(end_text)
                if suffix_length <= 0 or total_size <= 0:
                    raise ValueError("unsatisfiable range")
                start = max(total_size - suffix_length, 0)
                end = total_size - 1
            else:
                if not start_text.isdigit():
                    raise ValueError("invalid range start")
                start = int(start_text)
                if end_text:
                    if not end_text.isdigit():
                        raise ValueError("invalid range end")
                    end = int(end_text)
                else:
                    end = total_size - 1
                if start > end or start >= total_size:
                    raise ValueError("unsatisfiable range")
                end = min(end, total_size - 1)

            return start, end

        def send_range_not_satisfiable(self, total_size):
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes */{total_size}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def send_head(self):
            path = self.translate_path(self.path)
            if os.path.isdir(path):
                return super().send_head()

            if path.endswith("/"):
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return None

            try:
                handle = open(path, "rb")
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return None

            try:
                stat_result = os.fstat(handle.fileno())
                total_size = stat_result.st_size
                content_type = self.guess_type(path)
                last_modified = self.date_time_string(stat_result.st_mtime)
                range_header = self.headers.get("Range")

                if range_header:
                    try:
                        start, end = self.parse_range(range_header, total_size)
                    except ValueError:
                        handle.close()
                        self.send_range_not_satisfiable(total_size)
                        return None

                    handle.seek(start)
                    content_length = end - start + 1
                    self.send_response(HTTPStatus.PARTIAL_CONTENT)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                    self.send_header("Content-Length", str(content_length))
                    self.send_header("Last-Modified", last_modified)
                    self.end_headers()
                    return RangeReader(handle, content_length)

                if "If-Modified-Since" in self.headers and "If-None-Match" not in self.headers:
                    try:
                        modified_since = email.utils.parsedate_to_datetime(
                            self.headers["If-Modified-Since"]
                        )
                    except (TypeError, IndexError, OverflowError, ValueError):
                        pass
                    else:
                        if modified_since.tzinfo is None:
                            modified_since = modified_since.replace(tzinfo=timezone.utc)
                        if modified_since.tzinfo is timezone.utc:
                            last_modified_dt = datetime.fromtimestamp(
                                stat_result.st_mtime, timezone.utc
                            ).replace(microsecond=0)
                            if last_modified_dt <= modified_since:
                                self.send_response(HTTPStatus.NOT_MODIFIED)
                                self.send_header("Accept-Ranges", "bytes")
                                self.end_headers()
                                handle.close()
                                return None

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(total_size))
                self.send_header("Last-Modified", last_modified)
                self.end_headers()
                return handle
            except Exception:
                handle.close()
                raise

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/manual-edits":
                self.send_json(200, self.ensure_edits())
                return
            super().do_GET()

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in {"/api/manual-edits/exclude", "/api/manual-edits/category"}:
                self.send_error(404, "Unknown API")
                return

            try:
                body = self.read_body_json()
                video_id = str(body.get("id") or "").strip()
                if not video_id:
                    raise ValueError("missing id")

                edits = self.ensure_edits()
                timestamp = now_iso()

                if path == "/api/manual-edits/exclude":
                    edits["excluded"][video_id] = {
                        "reason": str(body.get("reason") or "manual"),
                        "updated_at": timestamp,
                    }
                else:
                    category = normalize_category(body.get("category"))
                    edits["category_overrides"][video_id] = {
                        "category": category,
                        "previous_category": str(body.get("previous_category") or ""),
                        "updated_at": timestamp,
                    }

                edits["updated_at"] = timestamp
                write_json(manual_path, edits)
                self.send_json(200, {"ok": True, "edits": edits})
            except (json.JSONDecodeError, ValueError) as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
            except OSError as exc:
                self.send_json(500, {"ok": False, "error": str(exc)})

    return VideoLibraryHandler


def main():
    parser = argparse.ArgumentParser(description="Serve the local video library with write APIs for manual edits.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument("--root", default=".", help="Project root to serve.")
    args = parser.parse_args()

    project_root = Path(args.root).resolve()
    handler = make_handler(project_root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {project_root} at http://{args.host}:{args.port}/index.html")
    print("Manual edit API: /api/manual-edits")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
