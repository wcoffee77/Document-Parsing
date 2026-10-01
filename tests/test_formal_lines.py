"""정식보고서 줄 맞춤·주석 정규화·굵기·txt 제목 인식 (2026-10-01 사용자 실측 반영)."""

from __future__ import annotations

import pytest
from docx import Document as OpenDocx
from docx.shared import Pt, RGBColor

from doc2report.ir import Document, Heading, Paragraph, Run
from doc2report.layout.lines import fit_text
from doc2report.parsers.plaintext import text_to_markdown
from doc2report.pipeline import convert_document
from doc2report.profile import load_profile
from doc2report.render import docx_writer
from doc2report.transform.structure import normalize_annotations

W = {"narrow": 5.0, "wide": 10.0}  # 한글 10, 반각(공백·숫자) 5 — 바탕체처럼


def widths(text: str) -> list[float]:
    return [W["narrow"] if c == " " or c.isascii() else W["wide"] for c in text]


# ── 줄 나눔 알고리즘 ─────────────────────────────────────────────────

def test_short_text_stays_one_line():
    text = "가나다 라마바"
    lines = fit_text(text, widths(text), first_room=200, cont_room=200)
    assert [(l.start, l.end, l.steps) for l in lines] == [(0, len(text), 0)]


def test_slight_overflow_is_condensed_not_wrapped():
    text = "가나다 라마바"                                   # 폭 = 6*10 + 5 = 65
    lines = fit_text(text, widths(text), first_room=62, cont_room=62, max_condense=1.0, step=0.25)
    assert len(lines) == 1 and lines[0].steps == 2         # 넘침 3 / 글자 7개 = 0.43 → 0.25 단위로 올림 = 2단계(0.5)
    lines = fit_text(text, widths(text), first_room=40, cont_room=40, max_condense=1.0, step=0.25)
    assert len(lines) == 2                                  # 너무 많이 넘치면 줄을 나눈다


def test_wraps_at_word_boundary_with_continuation_room():
    text = "가나다 라마바 사아자 차카타"
    lines = fit_text(text, widths(text), first_room=75, cont_room=95)
    assert [text[l.start:l.end] for l in lines] == ["가나다 라마바", "사아자 차카타"]


def test_overlong_word_is_split_by_characters():
    text = "가나다라마바사아"
    lines = fit_text(text, widths(text), first_room=35, cont_room=35)
    assert [text[l.start:l.end] for l in lines] == ["가나다", "라마바", "사아"]


def test_margin_keeps_the_line_shorter():
    text = "가나다 라마바"
    assert len(fit_text(text, widths(text), first_room=65, cont_room=65)) == 1
    assert len(fit_text(text, widths(text), first_room=65, cont_room=65, margin=0.1)) == 2


# ── 주석 정규화 ──────────────────────────────────────────────────────

def test_annotation_marker_is_unified_and_text_rules_skip_it():
    doc = Document(blocks=[Paragraph(runs=[Run("(주석) 최근 평가 상위 이상")]),
                           Paragraph(runs=[Run("* 이미 표준 표시")])])
    out, changes = normalize_annotations(doc, ["*", "(주석)"], "*")
    assert [b.runs[0].text + "".join(r.text for r in b.runs[1:]) for b in out.blocks] == [
        "* 최근 평가 상위 이상", "* 이미 표준 표시"]
    assert [c.rule for c in changes] == ["주석 표시 통일"]


# ── 렌더: 굵기·주석·줄 맞춤 ───────────────────────────────────────────

class _FakeMeasurer:
    """바탕체처럼 한글 1em, 반각 0.5em (글꼴 파일이 없는 환경용)."""
    font_available = True

    def __init__(self, spec, bold):
        self.size = spec.size

    def char_width(self, ch):
        return self.size * (0.5 if ch == " " or ch.isascii() else 1.0)

    def width(self, text):
        return sum(self.char_width(c) for c in text)

    def line_height(self, multiplier=1.0):
        return self.size * 1.15 * multiplier


@pytest.fixture()
def fake_fonts(monkeypatch):
    monkeypatch.setattr(docx_writer.DocxRenderer, "_measurer",
                        lambda self, spec, bold: _FakeMeasurer(spec, bold))


def _render(tmp_path, blocks):
    out = tmp_path / "o.docx"
    convert_document(Document(blocks=blocks), out, load_profile("formal"), polish="none")
    return OpenDocx(str(out)).paragraphs


def test_original_markers_are_bold_for_formal(tmp_path):
    paragraphs = _render(tmp_path, [Heading(level=2, runs=[Run("추진 배경")]),
                                    Paragraph(runs=[Run("□ 핵심인력 선정")]),
                                    Paragraph(runs=[Run("- 세부 내용")])])
    bold = {p.text.strip(): all(r.bold for r in p.runs) for p in paragraphs}
    assert bold["1. 추진 배경"] and bold["□ 핵심인력 선정"] and not bold["- 세부 내용"]


def test_other_profiles_keep_original_marker_weight(tmp_path):
    out = tmp_path / "d.docx"
    convert_document(Document(blocks=[Heading(level=2, runs=[Run("추진")]),
                                      Paragraph(runs=[Run("□ 항목")])]),
                     out, load_profile("default"), polish="none")
    item = next(p for p in OpenDocx(str(out)).paragraphs if "항목" in p.text)
    assert not any(r.bold for r in item.runs)


def test_paren_annotation_becomes_blue_annotation(tmp_path):
    paragraphs = _render(tmp_path, [Heading(level=2, runs=[Run("추진 배경")]),
                                    Paragraph(runs=[Run("□ 핵심인력")]),
                                    Paragraph(runs=[Run("(주석) 최근 평가 상위 이상")])])
    note = next(p for p in paragraphs if "최근 평가" in p.text)
    assert note.text == "    * 최근 평가 상위 이상"
    run = next(r for r in note.runs if "최근" in r.text)
    assert run.font.size == Pt(10) and run.font.color.rgb == RGBColor(0, 0, 255)


def test_long_item_is_split_and_aligned_under_text(tmp_path, fake_fonts):
    long = " ".join(["가나다라마바사아"] * 12)                      # 한 줄(약 170mm)을 넘는 문장
    paragraphs = _render(tmp_path, [Heading(level=2, runs=[Run("추진 배경")]),
                                    Paragraph(runs=[Run("□ " + long)])])
    items = [p for p in paragraphs if p.text.strip() and not p.text.startswith("1.")]
    assert len(items) >= 2
    first, second = items[0], items[1]
    assert first.text.startswith("  □ ")
    # 접두 "  □ " = 반각 2 + 전각 □(반각 2) + 반각 1 = 5칸 → 둘째 줄은 공백 5칸으로 글자 시작에 맞춘다
    assert second.text.startswith(" " * 5) and not second.text.startswith(" " * 6)
    assert first.paragraph_format.keep_with_next and not items[-1].paragraph_format.keep_with_next


def test_slight_overflow_condenses_instead_of_wrapping(tmp_path, fake_fonts):
    prof = load_profile("formal")
    usable = prof.page.usable_width
    per = prof.font("body").size                                    # 전각 1글자 = 1em
    count = int(usable / per) - 3                                   # 접두("  □ ", 공백 포함) 폭을 빼면 딱 1글자쯤 넘침
    body = "가" * (count + 1)
    paragraphs = _render(tmp_path, [Heading(level=2, runs=[Run("추진 배경")]),
                                    Paragraph(runs=[Run("□ " + body)])])
    items = [p for p in paragraphs if "가" in p.text]
    assert len(items) == 1                                          # 줄을 안 나눴다
    spacing = [r._r.rPr.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}spacing") for r in items[0].runs]
    values = [int(x.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"))
              for x in spacing if x is not None]
    assert values and all(-10 <= v <= -2 for v in values)           # 0.1~0.5pt = -2~-10 (1/20pt)


# ── 서식 없는 txt: 제목·날짜 ──────────────────────────────────────────

def test_txt_title_and_date_are_recognised():
    md = text_to_markdown("인재 운영 현황 보고\n\n2026. 10. 1\n\n1. 추진 배경\n")
    assert md.splitlines()[0] == "# 인재 운영 현황 보고"
    assert not text_to_markdown("1. 추진 배경\n2026. 10. 1\n").startswith("# ")   # 말머리 줄은 제목이 아님


def test_star_right_after_a_table_is_still_a_blue_annotation(tmp_path):
    from doc2report.pipeline import convert

    src = tmp_path / "s.txt"
    src.write_text("1. 현황\n\n구분\t현황\nA\t양호\n* 표 아래 설명\n※ 표 아래 참고\n", encoding="utf-8")
    out = tmp_path / "s.docx"
    convert(str(src), out, "formal", polish="none")
    paragraphs = {p.text.strip(): p for p in OpenDocx(str(out)).paragraphs}
    star = paragraphs["* 표 아래 설명"]
    run = star.runs[-1]
    assert run.font.size == Pt(10) and run.font.color.rgb == RGBColor(0, 0, 255)
    note = paragraphs["※ 표 아래 참고"]
    assert note.runs[-1].font.size in (None, Pt(14)) and not (
        note.runs[-1].font.color and note.runs[-1].font.color.type and
        note.runs[-1].font.color.rgb == RGBColor(0, 0, 255))


# ── 주석 텍스트 상자 ──────────────────────────────────────────────────

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_V_NS = "{urn:schemas-microsoft-com:vml}"


def test_annotation_becomes_a_text_box_under_the_line(tmp_path, fake_fonts):
    from doc2report.guide_mining.probe import probe_docx

    out = tmp_path / "box.docx"
    convert_document(Document(blocks=[
        Heading(level=2, runs=[Run("추진 배경")]),
        Paragraph(runs=[Run("□ 핵심인력 선정")]),
        Paragraph(runs=[Run("* 최근 평가 상위 이상, 영어회화 2급 이상")]),
        Paragraph(runs=[Run("□ 다음 항목")])]), out, load_profile("formal"), polish="none")
    paragraphs = OpenDocx(str(out)).paragraphs
    texts = [p.text.strip() for p in paragraphs]
    assert not any("영어회화" in t for t in texts)                        # 본문 문단으로는 안 나온다
    anchor = next(p for p in paragraphs if "핵심인력" in p.text)
    shapes = list(anchor._p.iter(f"{_V_NS}shape"))
    assert len(shapes) == 1 and "영어회화" in "".join(anchor._p.itertext())
    style = shapes[0].get("style")
    assert "position:absolute" in style and "mso-position-vertical-relative:text" in style
    prof = load_profile("formal")
    line = prof.font("body").size * 1.15 * prof.font("body").line_spacing
    assert anchor.paragraph_format.space_after >= prof.font("annotation").size   # 상자 높이만큼 아래를 비움
    assert f"margin-top:{line / 12700:.2f}pt" in style                          # 윗줄 바로 아래
    probe = probe_docx(out)                                                    # Word가 읽는 구조인지: 우리 probe로 되읽기
    box = probe.textboxes[0]
    assert box.kind == "vml" and box.floating and box.border == "none" and box.fill == "none"
    note = next(p for p in probe.paragraphs if p.where == "textbox")
    assert (note.fmt.size_pt, note.fmt.color) == (10.0, "0000FF")


def test_annotation_falls_back_to_a_paragraph_without_anchor(tmp_path, fake_fonts):
    out = tmp_path / "fallback.docx"
    convert_document(Document(blocks=[Paragraph(runs=[Run("* 맨 앞 주석")])]),
                     out, load_profile("formal"), polish="none")
    (p,) = [p for p in OpenDocx(str(out)).paragraphs if "주석" in p.text]
    assert p.text.strip() == "* 맨 앞 주석" and not list(p._p.iter(f"{_V_NS}shape"))


def test_two_annotations_stack_under_the_same_line(tmp_path, fake_fonts):
    out = tmp_path / "two.docx"
    convert_document(Document(blocks=[
        Heading(level=2, runs=[Run("추진 배경")]), Paragraph(runs=[Run("□ 핵심인력")]),
        Paragraph(runs=[Run("* 첫째 설명")]), Paragraph(runs=[Run("* 둘째 설명")])]),
        out, load_profile("formal"), polish="none")
    anchor = next(p for p in OpenDocx(str(out)).paragraphs if "핵심인력" in p.text)
    tops = [float(s.get("style").split("margin-top:")[1].split("pt")[0]) for s in anchor._p.iter(f"{_V_NS}shape")]
    assert len(tops) == 2 and tops[1] > tops[0]


def test_wrapped_txt_lines_become_one_bold_sentence_aligned_under_text(tmp_path, fake_fonts):
    from doc2report.pipeline import convert

    first = " ".join(["가나다라마바사아"] * 7)          # 한 줄을 거의 채우는 길이
    src = tmp_path / "w.txt"
    src.write_text(f"1. 추진 배경\n□ {first}\n자차카타파하 마지막 줄\n□ 다음\n", encoding="utf-8")
    out = tmp_path / "w.docx"
    convert(str(src), out, "formal", polish="none")
    items = [p for p in OpenDocx(str(out)).paragraphs if p.text.strip() and not p.text.startswith("1.")]
    assert items[-1].text.strip() == "□ 다음"
    lines = items[:-1]
    assert len(lines) >= 2 and lines[0].text.startswith("  □ ") and lines[1].text.startswith(" " * 5)
    assert not any(l.text.lstrip().startswith("□") for l in lines[1:])        # 새 말머리가 붙지 않는다
    assert all(r.bold for l in lines for r in l.runs if r.text.strip())      # 둘째 줄도 굵게


# ── 2026-10-01 사용자 실사용 2차 보고 재현 ────────────────────────────

def _convert_txt(tmp_path, text, profile="formal", **kw):
    from doc2report.pipeline import convert

    src = tmp_path / "r.txt"
    src.write_text(text, encoding="utf-8")
    out = tmp_path / "r.docx"
    result = convert(str(src), out, profile, **kw)
    return OpenDocx(str(out)).paragraphs, result


def test_hard_line_breaks_are_kept_and_continuations_align_and_stay_bold(tmp_path, fake_fonts):
    paragraphs, _ = _convert_txt(tmp_path, (
        "1. 추진 배경\n"
        "□ 핵심인력 선정 기준을 마련하여 인사 운영 체계를 개선하며,\n"
        "평가 결과를 공정하게 반영하고,\n"
        "성과 연계를 강화함\n"
        "- 짧은 항목\n"
        "내려쓴 짧은 줄\n"
        "□ 다음 항목\n"))
    texts = [p.text for p in paragraphs]
    assert texts == ["1. 추진 배경",
                     "  □ 핵심인력 선정 기준을 마련하여 인사 운영 체계를 개선하며,",
                     " " * 5 + "평가 결과를 공정하게 반영하고,",           # 쉼표로 끝나도 "."로 안 바뀌고 윗줄 글자에 맞춘다
                     " " * 5 + "성과 연계를 강화함",                        # 셋째 줄도 같은 위치
                     "    - 짧은 항목",
                     " " * 6 + "내려쓴 짧은 줄",                             # 윗줄이 짧아도 이어짐
                     "  □ 다음 항목"]
    bold = [all(r.bold for r in p.runs if r.text.strip()) for p in paragraphs]
    assert bold[1:4] == [True, True, True] and bold[4:6] == [False, False]  # □ 문장은 모든 줄이 굵게, - 는 안 굵게


def test_formal_does_not_rewrite_the_text_by_default(tmp_path, fake_fonts):
    assert load_profile("formal").text.polish == "none"
    long = "기준을 마련하여 인사 운영 체계를 개선하고 평가 결과를 공정하게 반영하며 성과 연계를 강화하고,"  # 60자 넘는 문장
    paragraphs, result = _convert_txt(tmp_path, f"1. 추진 배경\n□ {long}\n다음 줄 내용\n")
    joined = "".join(p.text.strip() for p in paragraphs[1:])
    assert long.replace(" ", "") in joined.replace(" ", "") and "다음줄내용" in joined.replace(" ", "")
    assert "." not in joined and not result.changes


def test_star_variants_are_all_annotations_even_after_a_long_line(tmp_path, fake_fonts):
    paragraphs, result = _convert_txt(tmp_path, (
        "1. 추진 배경\n"
        "□ 핵심인력 선정 기준을 마련하여 인사 운영 체계를 개선하고 평가 결과를 공정하게 반영함\n"
        "*공백 없는 별표 주석\n"
        "＊전각 별표 주석\n"
        "* 일반 별표 주석\n"))
    body = [p.text for p in paragraphs]
    assert not any("주석" in t for t in body)                                   # 셋 다 본문이 아니라 텍스트 상자
    holders = [p for p in paragraphs if list(p._p.iter(f"{_V_NS}shape"))]
    assert len(holders) == 1 and len(list(holders[0]._p.iter(f"{_V_NS}shape"))) == 3   # 윗줄(마지막 줄)에 세 개
    boxes = "".join(holders[0]._p.itertext())
    assert all(k in boxes for k in ("공백 없는 별표 주석", "전각 별표 주석", "일반 별표 주석"))
    assert "* 전각 별표 주석" in boxes                                           # 표시는 "*"로 통일


def test_condense_budget_is_one_point(tmp_path):
    assert load_profile("formal").text.condense_max == 12700


def test_non_fitting_profiles_still_join_hard_breaks(tmp_path):
    from doc2report.pipeline import convert

    src = tmp_path / "d.txt"
    src.write_text("1. 추진 배경\n□ 핵심인력 선정 기준을 마련하며\n평가를 반영함\n", encoding="utf-8")
    out = tmp_path / "d.docx"
    convert(str(src), out, "default", polish="none")
    texts = [p.text for p in OpenDocx(str(out)).paragraphs]
    assert any("핵심인력 선정 기준을 마련하며 평가를 반영함" in t for t in texts)   # 줄 맞춤이 꺼진 서식은 예전처럼 한 문장


def test_fit_text_reports_how_much_narrowing_the_break_would_have_needed():
    text = "가나다 라마바 사아자"
    lines = fit_text(text, widths(text), first_room=62, cont_room=62, max_condense=0.5, step=0.25)
    assert [text[l.start:l.end] for l in lines] == ["가나다 라마바", "사아자"]
    assert lines[0].need > 0.5 and lines[1].need == 0.0                  # 첫 줄: 다음 어절을 넣으려면 0.5pt보다 더 좁혀야 했다
