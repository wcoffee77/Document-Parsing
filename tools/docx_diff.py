"""두 docx의 문서 수준 설정 차이만 출력한다(본문 글자는 읽지 않음).

    uv run python tools/docx_diff.py 사용자문서.docx out\\calibration.docx

settings.xml·styles.xml(Normal·기본값)·쪽 설정(sectPr)·첫 문단의 문단/글자 서식을 요소 단위로 풀어
다른 줄만 보인다. rsid·문서 id처럼 매번 달라지는 값은 뺀다.
"""

from __future__ import annotations

import difflib
import re
import sys
import zipfile

_NOISE = re.compile(r"rsid|w14:docId|w:rsid|paraId|textId|<w:proofState|<w:zoom|<w:bookmark")


def _lines(xml: str) -> list[str]:
    xml = re.sub(r"<\?xml[^>]*\?>", "", xml)
    xml = re.sub(r'\s(xmlns:\w+|mc:Ignorable)="[^"]*"', "", xml)
    return [line.strip() for line in re.sub(r"(?=<)", "\n", xml).splitlines()
            if line.strip() and not _NOISE.search(line)]


def _parts(path: str) -> dict[str, list[str]]:
    z = zipfile.ZipFile(path)
    styles = z.read("word/styles.xml").decode("utf8")
    doc = z.read("word/document.xml").decode("utf8")
    normal = re.findall(r'<w:style [^>]*w:styleId="Normal".*?</w:style>', styles, re.S)
    defaults = re.findall(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    sect = re.findall(r"<w:sectPr\b.*?</w:sectPr>", doc, re.S)
    # 본문 글자는 빼고 문단·글자 서식(pPr/rPr)만
    props = re.findall(r"<w:(?:pPr|rPr)>.*?</w:(?:pPr|rPr)>", re.sub(r"<w:t[ >][^<]*</w:t>", "", doc), re.S)
    return {
        "settings.xml": _lines(z.read("word/settings.xml").decode("utf8")),
        "styles: docDefaults": _lines("".join(defaults)),
        "styles: Normal": _lines("".join(normal)),
        "sectPr(쪽 설정)": _lines("".join(sect)),
        "문단·글자 서식(처음 6개)": _lines("".join(props[:6])),
    }


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    first, second = _parts(sys.argv[1]), _parts(sys.argv[2])
    print(f"--- {sys.argv[1]}\n+++ {sys.argv[2]}")
    for key in first:
        diff = [line for line in difflib.unified_diff(first[key], second[key], lineterm="", n=0)
                if not line.startswith(("---", "+++", "@@"))]
        print(f"\n[{key}] " + ("차이 없음" if not diff else f"차이 {len(diff)}줄"))
        for line in diff:
            print("  " + line)


if __name__ == "__main__":
    main()
