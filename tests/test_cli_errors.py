"""CLI가 읽을 수 없는 입력·빈 입력을 파이썬 오류 추적 없이 알려 주는지."""

from typer.testing import CliRunner

from doc2report.cli import app


def test_fake_docx_gives_one_line_error_not_traceback(tmp_path):
    bad = tmp_path / "drm.docx"
    bad.write_bytes(b"not a zip at all")
    result = CliRunner().invoke(app, ["convert", str(bad), "-o", str(tmp_path / "out.docx")])
    assert result.exit_code == 1
    assert "[오류]" in result.output and "DRM" in result.output
    assert isinstance(result.exception, SystemExit)  # Traceback을 일으킨 예외가 아니라 정상적인 종료
    assert not (tmp_path / "out.docx").exists()


def test_missing_docx_is_reported(tmp_path):
    from doc2report.parsers.docx_reader import UnreadableDocx, parse_docx

    try:
        parse_docx(tmp_path / "none.docx")
    except UnreadableDocx as exc:
        assert "열 수 없습니다" in str(exc)
    else:
        raise AssertionError("UnreadableDocx가 나와야 한다")


def test_empty_input_warns(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("\n\n  \n​\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["convert", str(empty), "-o", str(tmp_path / "e.docx")])
    assert result.exit_code == 0
    assert "변환할 내용이 없습니다" in result.output


def test_normal_input_has_no_empty_warning(tmp_path):
    src = tmp_path / "ok.md"
    src.write_text("# 제목\n\n- 내용\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["convert", str(src), "-o", str(tmp_path / "o.docx")])
    assert result.exit_code == 0 and "변환할 내용이 없습니다" not in result.output
