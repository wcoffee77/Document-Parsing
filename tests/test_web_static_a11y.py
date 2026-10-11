"""웹 화면 정적 파일의 접근성·첫 사용 흐름 회귀 방지 (2026-10-11 디자인 점검 P1)."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "doc2report" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def test_first_visit_does_not_force_the_account_dialog():
    # 처음 쓰는 사람에게 등록 창을 강제로 띄우면 토큰이 필요 없는 서식 변환도 막힌다
    assert "if (!state.status.account.registered) openAccount();" not in JS
    assert 'id="setup-hint"' in HTML and 'id="setup-open"' in HTML


def test_tabs_follow_the_aria_tab_pattern():
    tabs = re.findall(r'<button class="tab[^"]*"[^>]*>', HTML)
    assert len(tabs) == 3
    assert all('aria-selected="' in t and "aria-controls=" in t and "tabindex=" in t for t in tabs)
    assert len(re.findall(r'role="tabpanel"', HTML)) == 3
    assert "ArrowRight" in JS and "Home" in JS and "End" in JS


def test_free_inputs_have_accessible_names():
    for ident in ("cf-urls", "tx-title", "tx-body", "date-pick"):
        tag = re.search(rf'<(?:input|textarea)[^>]*id="{ident}"[^>]*>', HTML)
        assert tag and "aria-label=" in tag.group(0), ident


def test_convert_reasons_are_next_to_the_button_and_announced():
    assert HTML.index('id="convert-note"') < HTML.index('id="convert"')
    assert 'aria-live="polite"' in HTML.split('id="convert-note"')[1].split(">")[0]
    assert 'aria-live="polite"' in HTML.split('id="toast"')[1].split(">")[0]
    # 입력 확인 오류는 몇 초 뒤 사라지는 토스트가 아니라 버튼 위 안내로 남는다
    assert 'toast("입력을 하나 이상' not in JS


def test_small_text_and_touch_targets():
    assert not re.search(r"font-size:\s*1[01]px", CSS)
    assert re.search(r"\.check\s*\{[^}]*min-height:\s*32px", CSS)
    assert re.search(r"\.btn\.tiny\s*\{[^}]*min-height:\s*32px", CSS)


def test_p2_layout_rules():
    # 실행 버튼과 안내는 한 덩어리(하단 고정 바)
    bar = HTML.split('class="actionbar"')[1].split("</div>")[0]
    assert 'id="convert-note"' in bar and 'id="convert"' in bar
    assert re.search(r"\.actionbar\s*\{[^}]*position:\s*sticky", CSS)
    # 카드가 옆 카드 높이로 늘어나 빈 흰 공간이 생기지 않게
    assert re.search(r"\.layout\s*\{[^}]*align-items:\s*start", CSS)
    # 체크박스·라디오 줄은 grid — 글자가 길어 줄이 바뀌어도 버튼과 어긋나지 않는다
    assert re.search(r"\.check\s*\{[^}]*display:\s*grid", CSS)
    # 파일 카드는 이름 줄 + 버튼 줄(파일명이 'x' 한 글자만 따로 남던 것)
    assert "overflow-wrap: anywhere" in CSS and 'class="acts"' in JS
    # 모바일 탭은 한 줄
    assert re.search(r"\.tab\s*\{[^}]*white-space:\s*nowrap", CSS)
