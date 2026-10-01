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
        _dist_rows("본문 글자 색", fonts["body"]["color"]),
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
    rows = ["| 말머리(층, 얕은 순) | 건수 | 왼쪽(mm) | 첫줄(mm) | 앞 공백 | 크기(pt) | 굵게 | 뒤 구분 | 글자수 p50 | 종결 형태 | 마침표 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in mk["by_marker"]:
        rows.append(f"| {r['marker']} | {r['count']} | {r['left_mm_median']} | {r['first_line_mm_median']} | "
                    f"{r['leading_spaces_median']} | {r['size_pt_median']} | {r['bold_share']} | {r['sep']} | "
                    f"{(r['text_len'] or {}).get('p50')} | "
                    f"{_endings(r['ending_class'])} | "
                    f"{r['period_ended_share']} |")
    detail: list[str] = []
    for r in mk["by_marker"]:
        if r["count"] < 3:
            continue
        detail += [f"- **{r['marker']}** (n={r['count']})",
                   *_dist_rows("  앞 공백 수", r["leading_spaces"]),
                   f"  - 전각 공백이 섞인 비율 {r['leading_wide_share']}",
                   *_dist_rows("  굵기 모양(말머리 뒤)", r["bold_pattern"]),
                   *[f"  - 하위 항목 {label} → 굵기: " + ", ".join(
                       f"{e['value']} ({e['share']:.0%}, {e['count']})" for e in rows_)
                     for label, rows_ in r["bold_by_children"].items() if rows_],
                   *_dist_rows("  단락 앞(pt)", r["space_before_pt"]),
                   *_dist_rows("  단락 뒤(pt)", r["space_after_pt"]),
                   *_dist_rows("  줄간격", r["line"]),
                   *_dist_rows("  글자 색", r["color"]),
                   *_dist_rows("  끝 두 글자(2회 이상)", r["ending_tail"]),
                   f"  - 밑줄 비율 {r['underline_share']}"]
    lines += _section("말머리 체계 (계층별 실제 서식)", [rows, detail, [
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
    lines += _section("표기 관례", [[f"- 날짜: {nt['date_forms']}", f"- 수치: {nt['number_forms']}"],
                                    _dist_rows("날짜 모양(숫자는 9로 가림)", s["dates"]["shapes"])])
    tb = s["tables"]
    lines += _section("표", [[f"- 문서당 표 수 {_fmt(tb['per_doc'])}, 행 {_fmt(tb['rows'])}, 열 {_fmt(tb['cols'])}",
                             f"- 병합 셀이 있는 표 비율 {tb['merged_share']}, 중첩 표 {tb['nested']}개"],
                            _dist_rows("표 정렬", tb["jc"]), _dist_rows("머리행 수", tb["header_rows"]),
                            _dist_rows("머리행 음영(첫 칸 직접 음영)", tb["header_fill"]),
                            [f"- 칸 직접 음영 비율(표 평균): 첫 행 {tb['fill_first_row_mean']}, "
                             f"첫 열 {tb['fill_first_col_mean']}, 나머지 {tb['fill_other_mean']}"],
                            _dist_rows("음영 색", tb["fill_colors"]),
                            _dist_rows("표 스타일", tb["style"]),
                            _dist_rows("표 스타일의 첫 행 음영", tb["style_first_row_fill"]),
                            _dist_rows("표 스타일의 첫 행 굵게", tb["style_first_row_bold"]),
                            _dist_rows("'첫 행 강조' 켬", tb["look_first_row"]),
                            [f"- 표 너비 / 본문 폭: {_fmt(tb['width_vs_text'])}"],
                            _dist_rows("표 왼쪽 들여쓰기(mm)", tb["indent_mm"]),
                            _dist_rows("표 테두리", tb["borders"]),
                            [f"- 칸 테두리가 있는 칸 비율(표 평균): {tb['cell_border_mean']}"],
                            _dist_rows("칸 테두리 종류", tb["cell_border_kinds"]),
                            _dist_rows("표 바로 위 줄", tb["before_kind"]),
                            _dist_rows("표 바로 아래 줄", tb["after_kind"])])
    cell_blocks = []
    for key, c in s["table_cells"].items():
        cell_blocks += [[f"**{key}** — 문단 {c['count']}개, 글자 수 {_fmt(c['text_len'])}"],
                        _dist_rows("정렬", c["align"]), _dist_rows("굵기 모양", c["bold_pattern"]),
                        _dist_rows("크기(pt)", c["size_pt"]), _dist_rows("글자 색", c["color"])]
    lines += _section("표 칸 서식", cell_blocks)
    hf = s["headers_footers"]
    lines += _section("머리말·꼬리말", [
        [f"- {label}: 글 있음 {hf[k]['with_text_share']}, 쪽번호 필드 {hf[k]['page_field_share']}, 정렬 {hf[k]['align']}"
         for k, label in (("header", "머리말"), ("footer", "꼬리말"))],
        [f"- 첫 쪽 머리말·꼬리말이 다른 문서 {hf['title_page_docs']}건"]])
    un = s["unmarked"]
    lines += _section("말머리 없는 줄", [
        [f"- 말머리 없는 본문 줄 {un['count']}개, 글자 수 {_fmt(un['text_len'])}"],
        _dist_rows("시작 모양", un["opener"]), _dist_rows("서식 (정렬·크기·굵기·들여쓰기)", un["profile"]),
        _dist_rows("종결 형태", un["ending_class"])])
    sk = s["skeleton"]
    sk_rows = [f"- 앞에서 {e['position']}번째 줄: " + ", ".join(
        f"{r['value']} ({r['share']:.0%}, {r['count']})" for r in e["shapes"]) for e in sk["first"]]
    sk_rows += [f"- 뒤에서 {e['position']}번째 줄: " + ", ".join(
        f"{r['value']} ({r['share']:.0%}, {r['count']})" for r in e["shapes"]) for e in sk["last"]]
    lines += _section("문서 첫머리·말미 구성 (본문 기준, 빈 줄 제외)", [sk_rows])
    an = s["annotations"]
    lines += _section("주석 상자 (텍스트 상자)", [
        [f"- 상자 {an['boxes']}개, 있는 문서 {an['docs_with_boxes']}건, 문서당 {_fmt(an['per_doc'])}, "
         f"떠 있는 상자 비율 {an['floating_share']}",
         f"- 상자당 문단 {_fmt(an['paragraphs_per_box'])}, 글자 수 {_fmt(an['box_chars'])}",
         f"- 크기(mm): 너비 {_fmt(an['width_mm'])}, 높이 {_fmt(an['height_mm'])}"],
        _dist_rows("배치", an["placement"]), [f"- 쪽 왼쪽 끝에서 상자까지(mm): {_fmt(an['x_mm'])}",
         f"- 세로 어긋남(문단 기준, mm): {_fmt(an['v_offset_mm'])}"],
        _dist_rows("글 뒤로 보냄", an["behind"]),
        _dist_rows("줄바꿈 방식", an["wrap"]),
        _dist_rows("테두리", an["border"]), _dist_rows("상자 배경색", an["fill"]),
        _dist_rows("글꼴", an["east_asia"]), _dist_rows("크기(pt)", an["size_pt"]),
        _dist_rows("글자 색", an["color"]), _dist_rows("줄간격", an["line"]),
        _dist_rows("정렬", an["align"]),
        [f"- 굵은 글자 비중 {an['bold_share']}"],
        _dist_rows("상자 안 말머리", an["marker_inside"]),
        _dist_rows("종결 형태", an["ending_class"]), _dist_rows("끝 두 글자", an["ending_tail"]),
        [f"- 마침표로 끝난 문장 {an['period_ended_share']}"],
        _dist_rows("붙은 문단의 위치", an["anchor_where"]),
        _dist_rows("붙은 문단의 말머리", an["anchor_marker"]),
        [f"- 붙은 문단 글자 수 {_fmt(an['anchor_text_len'])}"]])
    st = s["structure"]
    lines += _section("문서 구성 요소", [[
        f"- 목차 있는 문서 {st['toc_docs']}건, 텍스트 상자가 있는 문서 {st['textbox_docs']}건 "
        f"(문서당 {_fmt(st['textboxes_per_doc'])}), 쪽 나눔 {_fmt(st['page_breaks_per_doc'])}, "
        f"제목 스타일을 쓴 문서 {st['heading_style_docs']}건"]])
    cs = s["charset"]
    lines += _section("글자 구성·기호", [
        [f"- 글자 비중: {cs['share']}",
         "- 자주 쓰인 기호: " + (", ".join(f"{e['value']}({e['count']})" for e in cs["symbols"]) or "(없음)"),
         "- 한자: " + (", ".join(f"{e['value']}({e['count']})" for e in cs["hanja"]) or "(없음)")]])
    ph = s.get("phrases")
    if ph is not None:
        total = s["docs"]["count"]

        def rows_of(items):
            return [{"value": r["value"], "share": r["docs"] / total, "count": r["docs"]} for r in items]

        lines += _section("여러 문서에 반복되는 말 (2건 이상 문서에 나온 것만, 괄호는 문서 수)", [
            _dist_rows("1.·Ⅰ. 제목", rows_of(ph["section_titles"])),
            _dist_rows("표 머리행·첫 열 용어", rows_of(ph["table_terms"])),
            _dist_rows("영문 약어·용어", rows_of(ph["latin_terms"]))])
    return "\n".join(lines) + "\n"


def _endings(rows: list[dict]) -> str:
    return ", ".join("{} {:.0%}".format(e["value"], e["share"]) for e in rows)


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
