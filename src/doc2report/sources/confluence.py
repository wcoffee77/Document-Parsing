"""Confluence 페이지 가져오기.

인증·매크로·첨부 처리는 이미 검증된 confluence-markdown-exporter 에 맡긴다.
    pip install doc2report[confluence]
인증 정보는 환경변수로만 받는다 (코드·프로파일에 넣지 않는다):
    CONFLUENCE_URL      https://회사.atlassian.net/wiki  (Server면 https://wiki.회사.com)
    CONFLUENCE_USERNAME 계정 이메일 (Cloud만)
    CONFLUENCE_API_TOKEN API 토큰 또는 PAT
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import LoadedSource

_PAGE_ID = re.compile(r"/pages/(\d+)")


def page_id_from_url(url: str) -> str | None:
    match = _PAGE_ID.search(url)
    if match:
        return match.group(1)
    if url.isdigit():
        return url
    return None


def load_confluence(url_or_id: str) -> LoadedSource:
    _require_credentials()
    exporter = shutil.which("confluence-markdown-exporter")
    if exporter is None:
        raise RuntimeError(
            "confluence-markdown-exporter 가 설치되어 있지 않습니다.\n"
            "  uv pip install confluence-markdown-exporter\n"
            "(또는 페이지를 Markdown으로 내려받아 파일 경로로 변환하세요.)"
        )

    target = page_id_from_url(url_or_id) or url_or_id
    out_dir = Path(tempfile.mkdtemp(prefix="doc2report-confluence-"))
    result = subprocess.run(
        [exporter, "page", target, str(out_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Confluence 내보내기 실패:\n{result.stderr.strip()}")

    files = sorted(out_dir.rglob("*.md"))
    if not files:
        raise RuntimeError(f"내보낸 Markdown이 없습니다: {out_dir}")
    page = files[0]
    return LoadedSource(
        text=page.read_text(encoding="utf-8"),
        name=url_or_id,
        base_dir=page.parent,
        notes=[f"Confluence 페이지를 {out_dir} 에 내려받아 변환함"],
    )


def _require_credentials() -> None:
    missing = [key for key in ("CONFLUENCE_URL", "CONFLUENCE_API_TOKEN")
               if not os.environ.get(key)]
    if missing:
        raise RuntimeError(
            "Confluence 인증 정보가 없습니다. 환경변수를 설정하세요: " + ", ".join(missing)
        )
