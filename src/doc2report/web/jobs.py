"""변환 작업 하나(입력 여러 개 → 결과 파일 여러 형식)를 백그라운드로 돌린다.

Confluence(PowerShell 우회)·LLM·PDF 변환은 수십 초 걸릴 수 있어 요청을 붙잡아 두지 않고
작업 ID를 돌려준 뒤 화면이 진행 상황을 물어 가게 한다.

결과 파일 이름: "YYYYMMDD_제목.docx". 이미 있으면 "_2", "_3"… — 한 작업의 docx·pdf·md·변경내역이
**같은 이름 줄기**를 쓰도록 모든 확장자를 함께 비워 둔 이름을 고른다.
"""

from __future__ import annotations

import re
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..pipeline import convert_document, load_document, merge_documents
from ..sources import LoadedSource, load_text
from ..transform.llm_polish import llm_status
from . import options as opts

REPORT_SUFFIX = "_변경내역"
OUTPUT_KINDS = {".docx": "docx", ".pdf": "pdf", ".md": "md"}
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_MAX_STEM = 60


@dataclass
class Job:
    id: str
    state: str = "running"  # running | done | error
    messages: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    started: float = field(default_factory=time.time)

    def say(self, message: str) -> None:
        self.messages.append(message)

    def to_json(self) -> dict:
        return {"id": self.id, "state": self.state, "messages": self.messages,
                "result": self.result, "error": self.error,
                "elapsed": round(time.time() - self.started, 1)}


SYNTH_RUNS = 3


class JobRunner:
    def __init__(self, output_dir: Path, upload_dir: Path):
        self.output_dir = output_dir
        self.upload_dir = upload_dir
        self.jobs: dict[str, Job] = {}
        self._names = threading.Lock()
        self._reserved: set[str] = set()

    def submit(self, payload: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12])
        self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, payload), daemon=True).start()
        return job

    def run_sync(self, payload: dict) -> Job:
        """테스트용 — 같은 스레드에서 끝까지."""
        job = Job(id=uuid.uuid4().hex[:12])
        self.jobs[job.id] = job
        self._run(job, payload)
        return job

    # ── 실제 변환 ───────────────────────────────────────────────────────

    def _run(self, job: Job, payload: dict) -> None:
        try:
            job.result = self._convert(job, payload)
            job.state = "done"
            job.say("완료")
        except Exception as exc:  # 화면에 그대로 보여 준다
            job.state = "error"
            job.error = str(exc) or exc.__class__.__name__
            job.say("실패: " + job.error)
            traceback.print_exc()

    def _convert(self, job: Job, payload: dict) -> dict:
        options = payload.get("options") or {}
        if options.get("task") == "synthesize":
            return self._synthesize(job, payload)
        inputs, notes = payload.get("inputs") or [], []
        docs, kinds = self._load(job, inputs, options, notes)

        # 여러 입력 합치기: continuous = 이어 붙이기(입력 제목을 절 제목으로), pages = 입력마다 새 쪽
        merge = options.get("merge") or ("pages" if options.get("page_breaks") else "continuous")
        title = (options.get("title") or "").strip() or None
        merged = merge_documents(docs, title=title, section_titles=True,
                                 page_breaks=merge == "pages")
        name = title or merged.title or next((d.title for d in docs if d.title), None)

        profile, polish, llm, decision = opts.build_profile(options, docs, kinds,
                                                            llm_ready=llm_status()["configured"])
        if decision:
            notes = [f"자동 판단: {reason}" for reason in decision.reasons] + notes
        out = self._write(job, merged, name, profile, options, notes, polish=polish, llm=llm, shorten=False)
        out.update({"task": "convert",
                    "decision": ({"reasons": decision.reasons, **decision.summary} if decision else None)})
        return out

    def _synthesize(self, job: Job, payload: dict) -> dict:
        """요약·종합 보고서 만들기(2026-10-09 사용자): 입력 1개면 요약, 2개 이상이면 종합. CLI summarize/synthesize와 같은 엔진 —
        LLM이 핵심을 고르고 다시 쓰며, 파이썬이 숫자·날짜·방향을 원문과 대조한다. 사용자 요청사항은 구성·분량·강조에만 반영된다."""
        from ..drafting import brief, problem_count
        from ..synthesis import DEFAULT_PAGES, brief_source, flatten, prepare, synthesize

        options = payload.get("options") or {}
        if not llm_status()["configured"]:
            raise ValueError("요약·종합 보고서는 LLM이 있어야 만들 수 있습니다 — 위의 사용자 등록에서 온프렘 LLM 주소·모델명을 넣으세요")
        inputs = payload.get("inputs") or []
        notes: list[str] = []
        docs, _ = self._load(job, inputs, options, notes)
        sources = [flatten(doc, (item.get("title") or item.get("name") or f"입력 {i}").strip())
                   for i, (doc, item) in enumerate(zip(docs, inputs), 1)]
        kind = "요약" if len(sources) == 1 else "종합"
        pages = _pages(options.get("pages"), DEFAULT_PAGES)
        runs = SYNTH_RUNS  # 고정: 3번까지 만들어 남은 문제가 가장 적은 것(0이면 바로 멈춤)
        title = (options.get("title") or "").strip() or None
        year = datetime.now().year

        best = None
        for attempt in range(1, runs + 1):
            job.say(f"LLM으로 {kind} 보고서 쓰는 중 ({attempt}/{runs}회) — 응답·사실 검증에 1~3분 걸릴 수 있음")
            candidate = synthesize(sources, pages=pages, title=title, year=year)
            if best is None or problem_count(candidate) < problem_count(best):
                best = candidate
            if problem_count(candidate) == 0:
                break
        result = best
        if result.mode != "rewrite":
            notes.append(f"LLM {kind}에 실패해 원문 문장을 그대로 늘어놓은 기본 구조로 만들었습니다 — 요약·재구성이 아닙니다")
        notes += [f"[{kind}] {n}" for n in result.notes]
        summary = brief(result, brief_source(prepare(sources, pages, title)), year)

        doc, load_notes = load_document(load_text(result.text, name=f"{kind} 보고서"))
        name = title or result.title or sources[-1].title
        merged = merge_documents([doc], title=name, section_titles=False)
        profile = opts.format_profile(options)
        # 검증을 거친 글이라 문구 규칙·교열 LLM은 다시 돌리지 않는다. 두세 글자 넘치는 줄만 LLM으로 줄인다(CLI와 같게)
        out = self._write(job, merged, name, profile, options, notes + load_notes, polish="none", llm=False, shorten=True)
        out.update({"task": "synthesize", "kind": kind, "mode": result.mode, "summary": summary,
                    "pages": f"{pages[0]}-{pages[1]}", "decision": None})
        return out

    def _load(self, job: Job, inputs: list[dict], options: dict, notes: list[str]) -> tuple[list, list[str]]:
        sources, kinds = self._sources(inputs)
        docs = []
        for index, source in enumerate(sources, 1):
            name = source.name if isinstance(source, LoadedSource) else source
            job.say(f"입력 읽는 중 ({index}/{len(sources)}): {name}")
            try:
                doc, source_notes = load_document(source, linked=options.get("linked", True),
                                                  progress=job.say)
            except Exception as exc:
                raise RuntimeError(f"{index}번 입력({name}) 읽기 실패: {exc}") from exc
            docs.append(doc)
            notes.extend(source_notes)
        return docs, kinds

    def _write(self, job: Job, merged, name, profile, options: dict, notes: list[str], *,
               polish: str, llm: bool, shorten: bool) -> dict:
        """변환·파일 쓰기(docx + 고른 형식 + 변경 내역)와 결과 요약 — 서식 변환과 요약·종합이 같이 쓴다."""
        stem = self._reserve(name or "보고서")
        try:
            docx_path = self.output_dir / f"{stem}.docx"
            job.say("문구·구조 규칙 적용 중")
            result = convert_document(merged, docx_path, profile, polish=polish, llm=llm,
                                      date=opts.date_text(options.get("date"), profile),
                                      notes=notes, progress=job.say, shorten=shorten)
            files = [docx_path.name]
            formats = set(options.get("formats") or [])
            if "md" in formats:
                from ..render.markdown_writer import write_markdown

                job.say("Markdown 쓰는 중")
                files.append(write_markdown(result.document, profile,
                                            self.output_dir / f"{stem}.md").name)
            if "pdf" in formats:
                from ..render.pdf import docx_to_pdf

                job.say("PDF로 바꾸는 중 (Word 사용)")
                try:
                    files.append(docx_to_pdf(docx_path, self.output_dir / f"{stem}.pdf").name)
                except Exception as exc:
                    result.notes.append(f"PDF 만들기 실패 — Word 문서만 저장함: {exc}")
            if options.get("report", True):
                report = self.output_dir / f"{stem}{REPORT_SUFFIX}.md"
                report.write_text(result.report(), encoding="utf-8")
                files.append(report.name)
        finally:
            with self._names:
                self._reserved.discard(stem)

        return {
            "stem": stem,
            "title": name,
            "files": [{"name": name, "kind": _kind(name)} for name in files],
            "notes": result.notes,
            "changes": [{"before": c.before, "after": c.after, "rule": c.rule}
                        for c in result.changes[:500]],
            "change_count": len(result.changes),
            "tables": len(result.layouts),
            "polish": polish,
            "llm": llm,
            "profile": (f"사용자 설정(출발: {profile.label or profile.name})"
                        if options.get("preset") == "custom" else profile.label or profile.name),
            "preset": options.get("preset") or "default",
        }

    def _sources(self, inputs: list[dict]) -> tuple[list, list[str]]:
        if not inputs:
            raise ValueError("입력이 없습니다 — Confluence 주소, Word 파일, 붙여넣은 글 중 하나 이상을 추가하세요")
        sources: list = []
        kinds: list[str] = []
        for index, item in enumerate(inputs, 1):
            kind = item.get("type")
            if kind == "confluence":
                url = (item.get("url") or "").strip()
                if not url:
                    raise ValueError(f"{index}번 입력: Confluence 주소가 비어 있습니다")
                sources.append(url)
            elif kind == "docx":
                path = self._upload_path(item.get("upload_id", ""))
                name = item.get("name") or path.name
                sources.append(LoadedSource(text="", name=name, base_dir=path.parent,
                                            format="docx", path=path, title=Path(name).stem))
            elif kind == "text":
                text = item.get("text") or ""
                if not text.strip():
                    raise ValueError(f"{index}번 입력: 붙여넣은 글이 비어 있습니다")
                loaded = load_text(text, name=f"붙여넣은 글 {index}")
                loaded.title = (item.get("title") or "").strip() or None
                sources.append(loaded)
            else:
                raise ValueError(f"{index}번 입력: 알 수 없는 종류 {kind!r}")
            kinds.append(kind)
        return sources, kinds

    def _upload_path(self, upload_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", upload_id or ""):
            raise ValueError("올린 파일을 찾을 수 없습니다 — 다시 올려 주세요")
        matches = list(self.upload_dir.glob(f"{upload_id}/*.docx"))
        if not matches:
            raise ValueError("올린 파일을 찾을 수 없습니다(서버를 다시 켰다면 다시 올려 주세요)")
        return matches[0]

    # ── 파일 이름 ───────────────────────────────────────────────────────

    def _reserve(self, title: str) -> str:
        base = f"{datetime.now():%Y%m%d}_{safe_name(title)}"
        with self._names:
            stem, n = base, 1
            while stem in self._reserved or _taken(self.output_dir, stem):
                n += 1
                stem = f"{base}_{n}"
            self._reserved.add(stem)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return stem


def _pages(value, default: tuple[int, int]) -> tuple[int, int]:
    """화면의 분량 선택("1-2", "3") → (하한, 상한) 쪽 수."""
    found = re.fullmatch(r"\s*(\d)\s*(?:[-~]\s*(\d))?\s*", str(value or ""))
    if not found:
        return default
    low, high = int(found.group(1)), int(found.group(2) or found.group(1))
    if not 1 <= low <= high <= 10:
        return default
    return low, high


def safe_name(title: str) -> str:
    name = _ILLEGAL.sub(" ", title)
    name = re.sub(r"\s+", "_", name.strip()).strip("._")
    return name[:_MAX_STEM] or "보고서"


def _taken(folder: Path, stem: str) -> bool:
    names = [f"{stem}{ext}" for ext in OUTPUT_KINDS] + [f"{stem}{REPORT_SUFFIX}.md", f"{stem}_files"]
    return any((folder / name).exists() for name in names)


def _kind(name: str) -> str:
    if name.endswith(f"{REPORT_SUFFIX}.md"):
        return "report"
    return OUTPUT_KINDS.get(Path(name).suffix.lower(), "file")


def history(folder: Path, limit: int = 5) -> list[dict]:
    """저장 폴더의 결과를 이름 줄기별로 묶어 최근 것부터 limit개(화면에는 5개만 — 2026-10-09 사용자)."""
    groups: dict[str, dict] = {}
    if not folder.exists():
        return []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in OUTPUT_KINDS:
            continue
        kind = _kind(path.name)
        stem = path.name[: -len(f"{REPORT_SUFFIX}.md")] if kind == "report" else path.stem
        group = groups.setdefault(stem, {"stem": stem, "mtime": 0.0, "files": []})
        group["files"].append({"name": path.name, "kind": kind})
        group["mtime"] = max(group["mtime"], path.stat().st_mtime)
    order = {"docx": 0, "pdf": 1, "md": 2, "report": 3}
    out = sorted(groups.values(), key=lambda g: g["mtime"], reverse=True)[:limit]
    for group in out:
        group["files"].sort(key=lambda f: order.get(f["kind"], 9))
        group["time"] = datetime.fromtimestamp(group["mtime"]).strftime("%Y-%m-%d %H:%M")
    return out
