"""모든 테스트가 개발자 PC의 실제 사용자 등록(토큰)을 읽거나 덮어쓰지 않게 보관 폴더를 임시로 돌린다."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_account_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DOC2REPORT_HOME", str(tmp_path_factory.mktemp("doc2report-home")))
