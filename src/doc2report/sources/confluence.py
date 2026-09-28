"""Confluence 페이지 가져오기 — REST API로 storage format(XHTML)을 직접 읽는다.

마크다운으로 한 번 내렸다 올리는 경로(예전엔 confluence-markdown-exporter에 의존했다)는
표의 병합 셀(rowspan/colspan) 정보를 잃는다. GFM 마크다운 표 문법에는 그걸 표현할 방법이
없기 때문이다. Confluence는 표 폭에 제약이 없어 사용자가 자유롭게 셀을 합치므로, 이
손실이 특히 크다. 그래서 REST API가 주는 storage XHTML을 곧장
parsers/confluence_storage.py 로 넘긴다.

인증 정보는 환경변수로만 받는다 (코드·프로파일에 넣지 않는다):
    CONFLUENCE_URL       https://회사.atlassian.net/wiki  (Server/DC면 https://wiki.회사.com)
    CONFLUENCE_USERNAME  계정 이메일 — 있으면 Cloud(API 토큰 + Basic 인증)로 인식
    CONFLUENCE_API_TOKEN API 토큰(Cloud) 또는 개인 액세스 토큰(Server/DC, USERNAME 없이 Bearer로 씀)

받는 URL은 숫자 페이지 ID를 담고 있어야 한다 (`/pages/123456`, `?pageId=123456`,
또는 페이지 ID 숫자 그 자체). `/x/AbCd` 같은 단축 링크는 그 자체로 리다이렉트라
REST API 한 번으로는 못 푼다 — 페이지를 열어 실제 URL(또는 "..." 메뉴의 페이지 ID)을
확인해서 넣어야 한다.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import httpx

from . import LoadedSource

_TIMEOUT = 30.0

# Cloud: https://x.atlassian.net/wiki/spaces/TEAM/pages/123456/제목
# Server/DC(고전 URL, 흔함): https://wiki.회사.com/pages/viewpage.action?pageId=123456
# Server/DC(짧은 링크): https://wiki.회사.com/x/AbCd — 이건 REST로 못 푼다(모듈 docstring 참고)
_PAGE_ID_PATTERNS = (
    re.compile(r"/pages/(\d+)(?:/|$)"),
    re.compile(r"[?&]pageId=(\d+)"),
)


def page_id_from_url(url: str) -> str | None:
    for pattern in _PAGE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    if url.isdigit():
        return url
    return None


def load_confluence(url_or_id: str) -> LoadedSource:
    base_url = _require("CONFLUENCE_URL")
    page_id = page_id_from_url(url_or_id)
    if page_id is None:
        raise RuntimeError(
            f"URL에서 페이지 ID를 못 찾았습니다: {url_or_id}\n"
            "'/pages/123456', '?pageId=123456' 형태이거나 페이지 ID 숫자 자체여야 합니다. "
            "('/x/AbCd' 같은 단축 링크는 지원하지 않습니다 — 페이지를 열어 실제 URL을 쓰세요.)"
        )

    with _client(base_url) as client:
        page = _get_page(client, page_id)
        storage = page.get("body", {}).get("storage", {}).get("value")
        if not storage:
            raise RuntimeError(
                f"페이지 {page_id}에 storage 본문이 없습니다. "
                "권한이 있는 페이지인지, 첨부파일이 아니라 페이지인지 확인하세요."
            )

        title = page.get("title") or url_or_id
        out_dir = Path(tempfile.mkdtemp(prefix="doc2report-confluence-"))
        notes = [f"Confluence 페이지 '{title}'를 REST API로 읽음 (id={page_id})"]
        notes.extend(_download_attachments(client, page_id, out_dir))

    return LoadedSource(
        text=storage,
        name=url_or_id,
        base_dir=out_dir,
        notes=notes,
        format="confluence_storage",
        title=title,
    )


def _client(base_url: str) -> httpx.Client:
    username = os.environ.get("CONFLUENCE_USERNAME")
    token = _require("CONFLUENCE_API_TOKEN")
    if username:
        auth = httpx.BasicAuth(username, token)  # Cloud: 이메일 + API 토큰
        headers = {}
    else:
        auth = None
        headers = {"Authorization": f"Bearer {token}"}  # Server/Data Center: PAT
    return httpx.Client(base_url=base_url.rstrip("/"), auth=auth, headers=headers,
                        timeout=_TIMEOUT, verify=True)


def _get_page(client: httpx.Client, page_id: str) -> dict:
    resp = client.get(f"/rest/api/content/{page_id}",
                      params={"expand": "body.storage,space,version"})
    _raise_for_status(resp, page_id)
    return resp.json()


def _download_attachments(client: httpx.Client, page_id: str, out_dir: Path) -> list[str]:
    """<ac:image>가 참조하는 첨부 이미지를 파일명 그대로 내려받는다.

    parsers/confluence_storage.py는 Image.src에 첨부파일명만 넣어 두므로,
    파이프라인의 이미지 경로 해석(base_dir 기준)이 그대로 통하게 이 폴더에 그 이름으로 저장한다.
    """
    resp = client.get(f"/rest/api/content/{page_id}/child/attachment",
                      params={"limit": 200, "expand": "version"})
    if resp.status_code != 200:
        return [f"첨부파일 목록을 가져오지 못함 (HTTP {resp.status_code}) — 이미지가 빠질 수 있음"]

    notes: list[str] = []
    for item in resp.json().get("results", []):
        filename = item.get("title")
        download = item.get("_links", {}).get("download")
        if not filename or not download:
            continue
        try:
            file_resp = client.get(download)
            file_resp.raise_for_status()
        except httpx.HTTPError as exc:
            notes.append(f"첨부파일 내려받기 실패({filename}): {exc}")
            continue
        (out_dir / filename).write_bytes(file_resp.content)
    return notes


def _raise_for_status(resp: httpx.Response, page_id: str) -> None:
    if resp.status_code == 401:
        raise RuntimeError("Confluence 인증 실패(401). CONFLUENCE_USERNAME/API_TOKEN을 확인하세요.")
    if resp.status_code == 403:
        raise RuntimeError(f"페이지 {page_id}에 접근 권한이 없습니다(403).")
    if resp.status_code == 404:
        raise RuntimeError(f"페이지 {page_id}를 찾을 수 없습니다(404). URL 또는 페이지 ID를 확인하세요.")
    if resp.status_code >= 400:
        raise RuntimeError(f"Confluence API 오류 (HTTP {resp.status_code}): {resp.text[:300]}")


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            "Confluence 인증 정보가 없습니다. 환경변수를 설정하세요: "
            "CONFLUENCE_URL, CONFLUENCE_API_TOKEN (Cloud는 CONFLUENCE_USERNAME도 필요)"
        )
    return value
