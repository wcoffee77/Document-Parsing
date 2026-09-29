"""doc2report 웹 화면 — 파이썬 표준 라이브러리(http.server)만 쓴다.

FastAPI 같은 웹 프레임워크를 쓰지 않는 이유: 사내 PC는 인터넷이 막혀 wheelhouse로 오프라인
설치를 한다. 패키지가 늘면 wheelhouse를 다시 만들어 옮겨야 한다 — 이 도구는 한 사람이 자기 PC에서
쓰는 화면이라 표준 라이브러리로 충분하다. 화면(static/)도 외부 CDN을 쓰지 않는다(사내망 차단).

보안: 기본으로 127.0.0.1에만 열린다(같은 PC에서만 접속). Confluence 토큰·LLM 주소가 이 서버
프로세스의 환경변수에 있으므로 다른 PC에 열지 않는다. 쓰기 요청(POST)은 전용 헤더
(X-Doc2Report)가 있어야 받는다 — 다른 사이트가 브라우저를 시켜 몰래 요청하는 것을 막는다.
파일 열기·내려받기는 저장 폴더 바로 아래 파일만 된다.
"""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from ..sources.confluence import confluence_status, fetch_page_title
from ..transform.llm_polish import llm_status, llm_try
from . import options as opts
from .jobs import JobRunner, history

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 50 * 1024 * 1024
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}
_CONTENT_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".md": "text/plain; charset=utf-8",
}


class App:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(tempfile.mkdtemp(prefix="doc2report-uploads-"))
        self.jobs = JobRunner(self.output_dir, self.upload_dir)

    def status(self) -> dict:
        from ..render.pdf import pdf_engine

        return {"confluence": confluence_status(), "llm": llm_status(),
                "pdf": pdf_engine(), "output_dir": str(self.output_dir)}

    def output_file(self, name: str) -> Path:
        """저장 폴더 바로 아래 파일만 — "../" 같은 경로로 폴더 밖을 못 가리키게."""
        path = (self.output_dir / name).resolve()
        if path.parent != self.output_dir or not path.is_file():
            raise FileNotFoundError(name)
        return path


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "doc2report"

        def log_message(self, fmt, *args):  # 콘솔을 요청 로그로 채우지 않는다
            pass

        # ── GET ─────────────────────────────────────────────────────────

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == "/favicon.ico":
                    return self._static("favicon.svg")
                if path in ("/", "/index.html"):
                    return self._static("index.html")
                if path.startswith("/static/"):
                    return self._static(path[len("/static/"):])
                if path == "/api/status":
                    return self._json(app.status())
                if path == "/api/profiles":
                    return self._json({"profiles": [opts.profile_info(n) for n in opts.profile_names()],
                                       "schema": opts.schema()})
                if path == "/api/history":
                    return self._json({"items": history(app.output_dir)})
                if path.startswith("/api/jobs/"):
                    job = app.jobs.jobs.get(path.rsplit("/", 1)[-1])
                    return self._json(job.to_json()) if job else self._error(404, "작업이 없습니다")
                if path.startswith("/files/"):
                    return self._file(unquote(path[len("/files/"):]))
                return self._error(404, "없는 주소입니다")
            except Exception as exc:
                return self._error(500, str(exc))

        # ── POST ────────────────────────────────────────────────────────

        def do_POST(self):
            path = urlparse(self.path).path
            if self.headers.get("X-Doc2Report") != "1":
                return self._error(403, "허용되지 않은 요청입니다")
            try:
                if path == "/api/upload":
                    return self._upload()
                body = self._body_json()
                if path == "/api/convert":
                    return self._json({"job": app.jobs.submit(body).id})
                if path == "/api/confluence/check":
                    page_id, title = fetch_page_title(body.get("url", ""))
                    return self._json({"ok": True, "page_id": page_id, "title": title})
                if path == "/api/llm/test":
                    sample = body.get("text") or "시스템 응답 속도를 개선하기 위해 인덱스를 재설계하였습니다."
                    return self._json({"ok": True, "before": sample, "after": llm_try(sample)})
                if path == "/api/open":
                    return self._json(_open(app, body.get("name", ""), folder=bool(body.get("folder"))))
                return self._error(404, "없는 주소입니다")
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc) or exc.__class__.__name__}, 400)

        # ── 도우미 ──────────────────────────────────────────────────────

        def _upload(self):
            length = int(self.headers.get("Content-Length") or 0)
            name = Path(unquote(self.headers.get("X-Filename") or "문서.docx")).name
            if not name.lower().endswith(".docx"):
                return self._json({"ok": False, "error": "Word(.docx) 파일만 올릴 수 있습니다 "
                                   "(.doc은 Word에서 .docx로 다시 저장해 주세요)"}, 400)
            if length <= 0 or length > MAX_UPLOAD:
                return self._json({"ok": False, "error": "파일이 비었거나 너무 큽니다(50MB 이하)"}, 400)
            upload_id = uuid.uuid4().hex
            folder = app.upload_dir / upload_id
            folder.mkdir(parents=True)
            target = folder / name
            target.write_bytes(self.rfile.read(length))
            if target.read_bytes()[:2] != b"PK":
                shutil.rmtree(folder, ignore_errors=True)
                return self._json({"ok": False, "error": "Word 파일로 읽을 수 없습니다 — 문서보안(DRM)이 "
                                   "걸린 파일이면 Word에서 열어 내용을 '글 붙여넣기'로 넣어 주세요"}, 400)
            return self._json({"ok": True, "upload_id": upload_id, "name": name, "size": length})

        def _body_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def _static(self, name: str):
            path = (STATIC / name).resolve()
            if path.parent != STATIC.resolve() or not path.is_file():
                return self._error(404, "없는 파일입니다")
            # Windows는 레지스트리 설정에 따라 .js/.css를 text/plain으로 추측하기도 해서
            # (그러면 브라우저가 스타일을 버린다) 화면 파일 형식은 직접 정한다.
            ctype = _STATIC_TYPES.get(path.suffix.lower()) or (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self._send(200, path.read_bytes(), ctype, cache=False)

        def _file(self, name: str):
            query = urlparse(self.path).query
            try:
                path = app.output_file(name)
            except FileNotFoundError:
                return self._error(404, "파일이 없습니다(지웠거나 옮겼을 수 있음)")
            ctype = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
            inline = path.suffix.lower() in (".pdf", ".md") and "download" not in query
            disposition = ("inline" if inline else "attachment") + f"; filename*=UTF-8''{quote(path.name)}"
            self._send(200, path.read_bytes(), ctype, extra={"Content-Disposition": disposition})

        def _json(self, data, status: int = 200):
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", cache=False)

        def _error(self, status: int, message: str):
            self._json({"ok": False, "error": message}, status)

        def _send(self, status, body: bytes, ctype: str, *, cache=True, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if not cache:
                self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _open(app: App, name: str, *, folder: bool) -> dict:
    """결과 파일(또는 저장 폴더)을 이 PC의 기본 프로그램으로 연다 — .docx는 Word로."""
    target = app.output_dir if folder and not name else app.output_file(name)
    system = platform.system()
    if system == "Windows":
        if folder and name:
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            os.startfile(str(target))  # type: ignore[attr-defined]  # Windows 전용
        return {"ok": True}
    opener = "open" if system == "Darwin" else shutil.which("xdg-open")
    if not opener:
        return {"ok": False, "error": "이 PC에서는 파일을 바로 열 수 없습니다 — 내려받기를 쓰세요"}
    subprocess.Popen([opener, str(target if target.is_dir() or not folder else target.parent)])
    return {"ok": True}


def create_server(host: str, port: int, output_dir: Path) -> tuple[ThreadingHTTPServer, App]:
    app = App(output_dir)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server, app


def serve(host: str = "127.0.0.1", port: int = 8765, output_dir: Path | None = None,
          open_browser: bool = True) -> None:
    output_dir = output_dir or Path(os.environ.get("DOC2REPORT_OUTPUT_DIR") or Path.cwd() / "out" / "webapp")
    server, app = create_server(host, port, output_dir)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{server.server_address[1]}/"
    print(f"doc2report 웹 화면: {url}")
    print(f"  결과 저장 폴더: {app.output_dir}")
    print("  끝내려면 이 창에서 Ctrl+C")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()
        shutil.rmtree(app.upload_dir, ignore_errors=True)
