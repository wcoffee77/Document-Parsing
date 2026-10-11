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


def test_dark_mode_uses_tokens_not_hardcoded_colors():
    # 다크 모드(prefers-color-scheme)가 있고, 색은 :root 토큰으로만 쓴다(하드코딩이 남으면 다크에서 흰 상자가 생긴다)
    assert "prefers-color-scheme: dark" in CSS
    assert "color-scheme: light dark" in CSS and 'name="color-scheme"' in HTML
    body = CSS.split("* { box-sizing", 1)[1]            # :root·다크 블록 뒤의 규칙들
    leftovers = [m for m in re.findall(r"#[0-9a-fA-F]{3,6}\b", body)]
    # 흰 글자(#fff)와 파일 종류 배지(진한 바탕 + 흰 글자)는 두 모드 공통이라 허용
    allowed = {"#fff", "#2b579a", "#c43e1c", "#444", "#6b7280"}
    assert not [c for c in leftovers if c.lower() not in allowed], leftovers


def test_dark_palette_text_contrast():
    def lum(h):
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

    def ratio(a, b):
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def tokens(block):
        return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))

    dark = tokens(CSS.split("prefers-color-scheme: dark")[1].split("}")[0])
    light = tokens(CSS.split("@media (prefers-color-scheme: dark)")[0])
    pairs = [("ink", "card"), ("ink", "bg"), ("ink", "surface"), ("muted", "card"), ("muted", "bg"), ("muted", "surface"),
             ("muted", "chip"), ("accent", "card"), ("accent", "accent-soft"), ("ok", "ok-soft"), ("warn", "warn-soft"),
             ("bad", "bad-soft"), ("ink", "code")]
    for mode, t in (("dark", dark), ("light", light)):
        for fg, bg in pairs:
            if fg in t and bg in t:
                assert ratio(t[fg], t[bg]) >= 4.5, (mode, fg, bg, round(ratio(t[fg], t[bg]), 2))
    # 흰 글자가 올라가는 바탕(버튼·알림)
    assert ratio("#ffffff", dark["accent-fill"]) >= 4.5 and ratio("#ffffff", light["bad-fill"]) >= 4.5
