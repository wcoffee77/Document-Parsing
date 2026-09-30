"""집계 요약 → 사람이 읽는 Markdown. 숫자는 그대로 옮기고 해석은 하지 않는다."""

from __future__ import annotations


def to_markdown(s: dict) -> str:
    lines = ["# 정식보고서 말뭉치 — 서식·형식·문장 통계", ""]
    docs = s["docs"]
    lines += [f"- 분석 문서 {docs['count']}건", ""]
    for note in docs.get("skipped", []) + docs["notes"]:
        lines.append(f"- ⚠ {note}")
    lines.append("")

    lines += _section("쪽 설정 (첫 구역)", [_dist_rows("여백·용지", s["page"]["layout"]),
                                          _dist_rows("머리말·꼬리말 거리", s["page"]["header_footer_distance"])])
    fonts = s["fonts"]
    lines += _section("글꼴 (글자 수 가중)", [
        _dist_rows("본문 글꼴", fonts["body"]["east_asia"]), _dist_rows("본문 크기(pt)", fonts["body"]["size_pt"]),
        _dist_rows("본문 장평(%)", fonts["body"]["char_scale_pct"]),
        _dist_rows("표 글꼴", fonts["table"]["east_asia"]), _dist_rows("표 크기(pt)", fonts["table"]["size_pt"]),
        [f"- 본문 굵은 글자 비중 {fonts['body_bold_share']}"],
    ])
    sp = s["spacing"]
    lines += _section("줄간격·단락 간격·정렬 (본문)", [
        _dist_rows("줄간격", sp["line"]), _dist_rows("단락 앞(pt)", sp["space_before_pt"]),
        _dist_rows("단락 뒤(pt)", sp["space_after_pt"]), _dist_rows("정렬", sp["align"])])
    bl = s["blank_lines"]
    lines += _section("빈 줄 (줄 띄우기를 빈 문단으로 하는가)", [
        [f"- 문서별 빈 문단 비율: {_fmt(bl['blank_ratio_per_doc'])}"],
        _dist_rows("연속 빈 줄", bl["consecutive_blank_runs"]),
        ["- 말머리 앞에 빈 줄이 있는 비율 (말머리: 표본 수 / 비율)"]
        + [f"  - {k}: n={v['n']}, {v['share']}" for k, v in bl["blank_before_marker"].items()],
        [f"- 보이지 않는 글자: {bl['invisible_chars'] or '없음'}"]])
    mk = s["markers"]
    rows = ["| 말머리 | 건수 | 왼쪽(mm) | 첫줄(mm) | 앞 공백 | 크기(pt) | 굵게 | 뒤 구분 | 글자수 p50 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in mk["by_marker"]:
        rows.append(f"| {r['marker']} | {r['count']} | {r['left_mm_median']} | {r['first_line_mm_median']} | "
                    f"{r['leading_spaces_median']} | {r['size_pt_median']} | {r['bold_share']} | {r['sep']} | "
                    f"{(r['text_len'] or {}).get('p50')} |")
    lines += _section("말머리 체계 (계층별 실제 서식)", [rows, [
        f"- 자동 번호 비율 {mk['auto_numbering_share']}, 말머리 없는 문단 비율 {mk['no_marker_paragraph_share']}, "
        f"Symbol/Wingdings 글머리가 든 문서 {mk['docs_with_pua_bullet']}건"]])
    text = s["text"]
    parts = []
    for where, label in (("body", "본문"), ("table", "표 셀")):
        t = text[where]
        parts += [[f"**{label}** — 항목 {t['items']}개, 글자 수 {_fmt(t['item_chars'])}, "
                   f"항목당 문장 수 {_fmt(t['sentences_per_item'])}, 마침표로 끝난 문장 {t['period_ended_share']}"],
                  _dist_rows(f"{label} 종결 형태", t["ending_class"]),
                  _dist_rows(f"{label} 끝 두 글자", t["ending_tail"])]
    lines += _section("문장 형태", parts)
    nt = s["notation"]
    lines += _section("표기 관례", [[f"- 날짜: {nt['date_forms']}", f"- 수치: {nt['number_forms']}"]])
    tb = s["tables"]
    lines += _section("표", [[f"- 문서당 표 수 {_fmt(tb['per_doc'])}, 행 {_fmt(tb['rows'])}, 열 {_fmt(tb['cols'])}",
                             f"- 병합 셀이 있는 표 비율 {tb['merged_share']}, 중첩 표 {tb['nested']}개"],
                            _dist_rows("표 정렬", tb["jc"]), _dist_rows("머리행 수", tb["header_rows"]),
                            _dist_rows("머리행 음영", tb["header_fill"])])
    hf = s["headers_footers"]
    lines += _section("머리말·꼬리말", [
        [f"- {label}: 글 있음 {hf[k]['with_text_share']}, 쪽번호 필드 {hf[k]['page_field_share']}, 정렬 {hf[k]['align']}"
         for k, label in (("header", "머리말"), ("footer", "꼬리말"))],
        [f"- 첫 쪽 머리말·꼬리말이 다른 문서 {hf['title_page_docs']}건"]])
    st = s["structure"]
    lines += _section("문서 구성 요소", [[
        f"- 목차 있는 문서 {st['toc_docs']}건, 텍스트 상자가 있는 문서 {st['textbox_docs']}건 "
        f"(문서당 {_fmt(st['textboxes_per_doc'])}), 쪽 나눔 {_fmt(st['page_breaks_per_doc'])}, "
        f"제목 스타일을 쓴 문서 {st['heading_style_docs']}건"]])
    return "\n".join(lines) + "\n"


def _section(title: str, blocks: list[list[str]]) -> list[str]:
    out = [f"## {title}", ""]
    for block in blocks:
        out += block + [""]
    return out


def _dist_rows(label: str, rows: list[dict]) -> list[str]:
    if not rows:
        return [f"- {label}: (없음)"]
    return [f"- {label}: " + ", ".join(f"{r['value']} ({r['share']:.0%}, {r['count']})" for r in rows)]


def _fmt(d: dict | None) -> str:
    if not d:
        return "(없음)"
    return f"n={d['n']} 최소{d['min']} p25={d['p25']} 중앙{d['p50']} p75={d['p75']} p90={d['p90']} 최대{d['max']}"
