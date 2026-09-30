"""정식보고서 말뭉치 분석(가이드라인 채굴) — 1단계: 서식·형식·문장 통계.

    probe.py   .docx 하나 → 실효 서식·빈 문단·말머리·머리말/꼬리말 등 (OOXML은 여기만)
    stats.py   여러 문서의 probe → 집계 요약 (원문 글자 없음)
    report.py  요약 → 사람이 읽는 Markdown

원문(말뭉치)과 결과물은 **저장소 밖**에 둔다. 기본 출력 폴더 `out/probe`는 .gitignore 대상이다.
"""

from __future__ import annotations

import json
from pathlib import Path

from .probe import DocProbe, probe_docx
from .report import to_markdown
from .stats import summarize

__all__ = ["collect_docx", "probe_all", "write_outputs"]


def collect_docx(paths: list[str | Path]) -> list[Path]:
    """파일과 폴더(하위 포함)에서 .docx를 모은다. Word 임시 파일(~$)은 뺀다."""
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found += sorted(p for p in path.rglob("*.docx") if not p.name.startswith("~$"))
        elif path.suffix.lower() == ".docx" and not path.name.startswith("~$"):
            found.append(path)
    return found


def probe_all(files: list[Path]) -> tuple[list[DocProbe], list[str]]:
    """문서마다 probe. 못 읽는 문서(DRM·손상)는 건너뛰고 이유를 돌려준다."""
    probes: list[DocProbe] = []
    skipped: list[str] = []
    for index, path in enumerate(files, start=1):
        doc_id = f"doc{index:03d}"
        try:
            with path.open("rb") as fh:
                if fh.read(2) != b"PK":
                    skipped.append(f"{doc_id}: zip이 아님(DRM·암호화 의심) — Word에서 열어 다시 저장한 사본이 필요")
                    continue
            probes.append(probe_docx(path, doc_id=doc_id))
        except Exception as exc:  # noqa: BLE001 — 한 문서가 죽어도 나머지는 계속
            skipped.append(f"{doc_id}: 읽기 실패 ({type(exc).__name__}: {exc})")
    return probes, skipped


def write_outputs(probes: list[DocProbe], skipped: list[str], out_dir: str | Path, *,
                  keep_text: bool = False, keep_names: bool = False, phrases: bool = True) -> Path:
    """probe_summary.json/.md 와 문서별 probe/<id>.json. 기본은 원문 글자·파일 이름을 뺀다."""
    out = Path(out_dir)
    (out / "probe").mkdir(parents=True, exist_ok=True)
    summary = summarize(probes, phrases=phrases)
    summary["docs"]["skipped"] = skipped
    (out / "probe_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "probe_summary.md").write_text(to_markdown(summary), encoding="utf-8-sig")
    for probe in probes:
        (out / "probe" / f"{probe.doc_id}.json").write_text(
            json.dumps(probe.to_dict(keep_text=keep_text, keep_name=keep_names),
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
    return out
