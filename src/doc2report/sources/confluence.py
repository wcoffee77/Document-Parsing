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

CONFLUENCE_URL은 REST 엔드포인트 앞의 기본 주소여야 한다(`/rest/api/content/...`는
코드가 붙인다). 회사에 따라 REST 전용 게이트웨이가 브라우저 주소와 다른 서브도메인에
있고(예: `wiki.회사.com`이 아니라 `api.confluence.회사.com`), 안내받은 주소 자체에
`/rest/api`가 이미 포함된 경우도 있다 — 둘 다 그대로 넣어도 되도록 `/rest/api` 접미사는
있으면 떼고 쓴다(`_normalize_base_url`).

받는 URL은 숫자 페이지 ID를 담고 있어야 한다 (`/pages/123456`, `?pageId=123456`,
또는 페이지 ID 숫자 그 자체). `/x/AbCd` 같은 단축 링크는 그 자체로 리다이렉트라
REST API 한 번으로는 못 푼다 — 페이지를 열어 실제 URL(또는 "..." 메뉴의 페이지 ID)을
확인해서 넣어야 한다.

사내망 우회(2026-09-29, 사내 PC 실측): 일부 사내망에서는 httpx 요청이 403으로
막히는데 PowerShell의 Invoke-WebRequest는 통과한다(다른 에이전트가 직접 검증). 정확한
원인은 모른다 — 인증서 신뢰 저장소 차이일 수도, 사내 보안 게이트웨이가 요청 형태(예:
User-Agent)로 걸러내는 것일 수도 있다. 원인을 모르는 채로 httpx 쪽을 계속 추측해
고치는 대신, **검증된 그 경로를 그대로 재현**한다: httpx가 403을 받으면(Windows에서만)
Invoke-WebRequest로 한 번 더 시도하고, 성공하면 그 결과를 쓰며 --report에 남긴다.
DOC2REPORT_CONFLUENCE_TRANSPORT=powershell 로 처음부터 이 경로를 강제할 수도 있다.
"""

from __future__ import annotations

import base64
import os
import platform
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import LoadedSource

_TIMEOUT = 30.0
_TRANSPORT_ENV = "DOC2REPORT_CONFLUENCE_TRANSPORT"  # 비어 있으면 자동, "powershell"이면 강제

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
    base_url = _normalize_base_url(_require("CONFLUENCE_URL"))
    page_id = page_id_from_url(url_or_id)
    if page_id is None:
        raise RuntimeError(
            f"URL에서 페이지 ID를 못 찾았습니다: {url_or_id}\n"
            "'/pages/123456', '?pageId=123456' 형태이거나 페이지 ID 숫자 자체여야 합니다. "
            "('/x/AbCd' 같은 단축 링크는 지원하지 않습니다 — 페이지를 열어 실제 URL을 쓰세요.)"
        )

    notes: list[str] = []
    with _client(base_url) as client:
        page = _get_page(client, page_id, notes)
        storage = page.get("body", {}).get("storage", {}).get("value")
        if not storage:
            raise RuntimeError(
                f"페이지 {page_id}에 storage 본문이 없습니다. "
                "권한이 있는 페이지인지, 첨부파일이 아니라 페이지인지 확인하세요."
            )

        title = page.get("title") or url_or_id
        out_dir = Path(tempfile.mkdtemp(prefix="doc2report-confluence-"))
        notes.insert(0, f"Confluence 페이지 '{title}'를 REST API로 읽음 (id={page_id})")
        notes.extend(_download_attachments(client, page_id, out_dir, notes))

    return LoadedSource(
        text=storage,
        name=url_or_id,
        base_dir=out_dir,
        notes=notes,
        format="confluence_storage",
        title=title,
    )


_REST_API_SUFFIX = re.compile(r"/rest/api/?$", re.IGNORECASE)


def _normalize_base_url(url: str) -> str:
    """끝의 슬래시와, 있다면 '/rest/api'까지 뗀다.

    안내받은 주소가 사람이 쓰는 위키 주소(`.../wiki`)일 수도, REST 게이트웨이
    주소(`.../rest/api/`)일 수도 있어서 둘 다 그대로 CONFLUENCE_URL에 넣어도
    되게 한다 — 코드가 항상 `/rest/api/content/...`를 새로 붙이기 때문이다.
    """
    return _REST_API_SUFFIX.sub("", url.rstrip("/"))


def _auth_header() -> dict[str, str]:
    """Bearer/Basic 어느 쪽이든 최종 Authorization 헤더 값 하나로 만든다.

    httpx 쪽(Client.headers)과 PowerShell 대체 경로 양쪽이 같은 값을 그대로
    쓸 수 있어야 해서, httpx의 auth= 객체 대신 처음부터 헤더로 계산해 둔다.
    """
    username = os.environ.get("CONFLUENCE_USERNAME")
    token = _require("CONFLUENCE_API_TOKEN")
    if username:
        basic = base64.b64encode(f"{username}:{token}".encode()).decode()
        return {"Authorization": f"Basic {basic}"}  # Cloud: 이메일 + API 토큰
    return {"Authorization": f"Bearer {token}"}  # Server/Data Center: PAT


def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers=_auth_header(), timeout=_TIMEOUT, verify=True)


# ── 응답 래퍼 (httpx.Response 또는 PowerShell 결과, 둘 다 같은 인터페이스) ──


@dataclass
class _Reply:
    status_code: int
    content: bytes

    def json(self):
        import json

        return json.loads(self.content.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _get_page(client: httpx.Client, page_id: str, notes: list[str]) -> dict:
    resp = _get(client, f"/rest/api/content/{page_id}", notes,
               params={"expand": "body.storage,space,version"})
    _raise_for_status(resp, page_id)
    return resp.json()


def _download_attachments(
    client: httpx.Client, page_id: str, out_dir: Path, notes: list[str]
) -> list[str]:
    """<ac:image>가 참조하는 첨부 이미지를 파일명 그대로 내려받는다.

    parsers/confluence_storage.py는 Image.src에 첨부파일명만 넣어 두므로,
    파이프라인의 이미지 경로 해석(base_dir 기준)이 그대로 통하게 이 폴더에 그 이름으로 저장한다.
    """
    resp = _get(client, f"/rest/api/content/{page_id}/child/attachment", notes,
               params={"limit": 200, "expand": "version"})
    if resp.status_code != 200:
        return [f"첨부파일 목록을 가져오지 못함 (HTTP {resp.status_code}) — 이미지가 빠질 수 있음"]

    data = resp.json()
    # 첨부 다운로드 경로는 REST API 호스트가 아니라 위키 자체를 기준으로 한 상대 경로일 수
    # 있다(REST 게이트웨이 서브도메인이 위키와 다른 회사에서 특히). 응답이 준 기준 주소가
    # 있으면 그걸 우선 쓴다.
    link_base = (data.get("_links") or {}).get("base", "")

    attach_notes: list[str] = []
    for item in data.get("results", []):
        filename = item.get("title")
        download = (item.get("_links") or {}).get("download")
        if not filename or not download:
            continue
        url = download if download.startswith(("http://", "https://")) else link_base + download
        try:
            file_resp = _get(client, url, notes)
            file_resp.raise_for_status()
        except Exception as exc:
            attach_notes.append(f"첨부파일 내려받기 실패({filename}): {exc}")
            continue
        (out_dir / filename).write_bytes(file_resp.content)
    return attach_notes


def _raise_for_status(resp, page_id: str) -> None:
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


# ── 전송 계층: httpx가 기본, 403이면(Windows에서만) PowerShell로 대체 ────────


def _get(client: httpx.Client, path: str, notes: list[str], *, params: dict | None = None):
    """httpx로 GET하되, 403을 받으면(또는 강제 설정이면) PowerShell로 다시 시도한다."""
    if _forced_powershell():
        return _fetch_via_powershell(client, path, params, notes, forced=True)

    resp = client.get(path, params=params)
    if resp.status_code == 403 and _is_windows():
        return _fetch_via_powershell(client, path, params, notes, forced=False, httpx_403=resp)
    return resp


def _forced_powershell() -> bool:
    return os.environ.get(_TRANSPORT_ENV, "").strip().lower() == "powershell"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _fetch_via_powershell(
    client: httpx.Client, path: str, params: dict | None, notes: list[str],
    *, forced: bool, httpx_403: httpx.Response | None = None,
):
    url = str(client.build_request("GET", path, params=params).url)
    try:
        content = _powershell_get(url, _auth_header())
    except Exception as exc:
        if httpx_403 is not None:
            notes.append(f"httpx 403 → PowerShell(Invoke-WebRequest) 대체 시도도 실패: {exc}")
            return httpx_403
        raise RuntimeError(f"PowerShell 요청 실패: {exc}") from exc

    if not forced:
        notes.append(
            "httpx 요청이 403으로 거부돼 PowerShell(Invoke-WebRequest)로 재시도해 성공함 "
            "— 이 사내망에서 필요한 우회 경로(2026-09-29 실측, 원인 미확정)"
        )
    return _Reply(status_code=200, content=content)


def _powershell_get(url: str, headers: dict[str, str]) -> bytes:
    """PowerShell Invoke-WebRequest로 GET해 원시 바이트를 돌려준다.

    Windows 인증서 저장소·TLS 스택을 그대로 쓰는 PowerShell이 httpx보다 사내망을
    잘 통과하는 경우가 있다(docs/onprem-first-run.md 2번에서 다른 호스트로도 확인된
    패턴). subprocess 출력은 텍스트 모드라 바이너리(이미지 등)가 깨질 수 있어
    Base64로 감싸 주고받는다.
    """
    # PowerShell 해시테이블 리터럴은 항목을 쉼표가 아니라 세미콜론으로 구분한다
    # (쉼표를 쓰면 값이 배열로 묶여 버린다).
    header_expr = "; ".join(
        f"'{_ps_escape(k)}'='{_ps_escape(v)}'" for k, v in headers.items()
    )
    script = (
        "$ProgressPreference = 'SilentlyContinue'; "
        f"$r = Invoke-WebRequest -Uri '{_ps_escape(url)}' -Headers @{{{header_expr}}} "
        "-UseBasicParsing; "
        "[Convert]::ToBase64String($r.RawContentStream.ToArray())"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError((result.stderr or result.stdout or "빈 응답").strip()[:300])
    return base64.b64decode(result.stdout.strip())


def _ps_escape(value: str) -> str:
    """PowerShell 작은따옴표 문자열 안에 안전하게 넣도록 작은따옴표만 이스케이프."""
    return value.replace("'", "''")
