"""입력 소스 어댑터 — 무엇을 읽든 결국 Markdown 텍스트로 만들어 파서에 넘긴다."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LoadedSource:
    text: str
    name: str  # 원본 경로/URL — 로그용
    base_dir: Path | None = None  # 이미지 등 상대 경로 기준
    notes: list[str] = field(default_factory=list)


def load_source(source: str) -> LoadedSource:
    if source == "-":
        return LoadedSource(text=sys.stdin.read(), name="<stdin>", base_dir=Path.cwd())
    if source.startswith(("http://", "https://")):
        from .confluence import load_confluence

        return load_confluence(source)
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없음: {path}")
    return LoadedSource(text=path.read_text(encoding="utf-8"), name=str(path),
                        base_dir=path.parent)
