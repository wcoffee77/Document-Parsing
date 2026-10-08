"""다문서 종합(D단계) 시험 중 사용자 지적(2026-10-08) — 원숫자 앞 말머리 중복, 글꼴 파일 없는 환경의 줄 맞춤."""

import pytest
from docx import Document as OpenDocx

from doc2report.layout.measure import TextMeasurer
from doc2report.pipeline import convert


def _texts(tmp_path, text):
    src = tmp_path / "s.txt"
    src.write_text(text, encoding="utf-8")
    out = tmp_path / "o.docx"
    result = convert(str(src), out, "formal", polish="none")
    return [p.text for p in OpenDocx(str(out)).paragraphs], result


@pytest.mark.parametrize("line", ["□ ① B사 : 단가 1,720만원", "- ① B사 : 단가 1,720만원", "□ (1) B사 : 단가 1,720만원"])
def test_marker_before_enumerated_number_is_dropped(tmp_path, line):
    paras, result = _texts(tmp_path, f"보고\n2026. 10. 7\n1. 현 황\n {line}\n   - 세부 내용\n")
    joined = "\n".join(paras)
    assert "□ ①" not in joined and "- ①" not in joined and "□ (1)" not in joined
    assert "B사 : 단가 1,720만원" in joined
    assert any(c.rule == "중복 말머리 제거" for c in result.changes)


def test_plain_symbol_markers_are_untouched(tmp_path):
    paras, _ = _texts(tmp_path, "보고\n2026. 10. 7\n1. 현 황\n □ 재고 : 180개\n   - 세부 내용\n")
    assert any(p.strip().startswith("□") for p in paras) and any("- 세부" in p for p in paras)


def test_fixed_pitch_font_without_file_is_measured_by_model():
    m = TextMeasurer("바탕체", "바탕체", 177800)          # 14pt — 이 샌드박스에는 글꼴 파일이 없다
    if m.font_available:
        pytest.skip("실제 바탕체가 설치된 환경")
    assert m.widths_known and m.widths_estimated
    assert m.width("가나") == pytest.approx(2 * 177800)    # 한글 1em
    assert m.width("ab 1") == pytest.approx(4 * 0.5 * 177800)  # 영문·숫자·공백 0.5em
    assert m.width("①") == pytest.approx(177800)           # 원숫자 1em(추정)
    assert not TextMeasurer("없는글꼴", "없는글꼴", 177800).widths_known
