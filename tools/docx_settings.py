"""docx의 문서 수준 설정만 출력한다(본문 글자는 읽지 않음) — 줄 폭이 문서마다 다른 원인을 찾는 용도.

    uv run python tools/docx_settings.py 파일1.docx [파일2.docx ...]
"""

from __future__ import annotations

import re
import sys
import zipfile


def main() -> None:
    for path in sys.argv[1:]:
        z = zipfile.ZipFile(path)
        settings = z.read("word/settings.xml").decode("utf8")
        styles = z.read("word/styles.xml").decode("utf8")
        doc = z.read("word/document.xml").decode("utf8")
        print(f"== {path}")
        for tag in ("characterSpacingControl", "themeFontLang", "useFELayout", "doNotCompress",
                    "adjustLineHeightInTable", "doNotUseEastAsianBreakRules", "kinsoku", "autoSpaceLikeWord95",
                    "snapToGrid"):
            print(f"settings {tag}:", re.findall(rf"<w:{tag}\b[^>]*>", settings) or "-")
        print("compat:", re.findall(r'<w:compatSetting [^>]*w:name="(\w+)"[^>]*w:val="(\d+)"', settings)
              or re.findall(r'<w:compatSetting [^>]*>', settings))
        print("docGrid:", re.findall(r"<w:docGrid[^>]*>", doc))
        print("docDefaults:", re.findall(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)[:1])
        normal = re.findall(r'<w:style [^>]*w:styleId="Normal".*?</w:style>', styles, re.S)
        print("Normal:", normal[:1])
        print("run spacing/kern/w:w:", sorted(set(re.findall(r"<w:(?:spacing w:val|kern w:val|w w:val)=\"[-\d]+\"", doc))))


if __name__ == "__main__":
    main()
