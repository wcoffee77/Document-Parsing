"""git 주소만 공유하는 배포(2026-10-14): runtime을 runtime-win64 브랜치에서 첫 실행 때 자동으로 받는다."""

from pathlib import Path

import yaml

from doc2report import doctor
from doc2report.doctor import INFO, OK, WARN

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8-sig")


def test_bat_files_are_ascii_and_call_ensure_runtime():
    # cmd는 코드 페이지 때문에 비ASCII 글자가 있으면 줄이 깨진다
    for name in ("start_webapp.bat", "doctor.bat", "scripts/ensure_runtime.bat"):
        assert (ROOT / name).read_bytes().isascii(), name
    for name in ("start_webapp.bat", "doctor.bat"):
        text = _read(name)
        assert 'call "%~dp0scripts\\ensure_runtime.bat"' in text
        assert text.index("ensure_runtime.bat") < text.index('if exist "%~dp0runtime\\python.exe"')   # 받은 뒤에 실행 파일을 찾는다


def test_ensure_runtime_skips_bundles_and_hand_copied_runtime():
    text = _read("scripts/ensure_runtime.bat")
    # 설치 묶음(.git 없음)과, 손으로 복사한 runtime(runtime\.git 없음)은 건드리지 않는다
    assert 'if not exist "%ROOT%\\.git" exit /b 0' in text
    assert 'if not exist "%ROOT%\\runtime\\.git" exit /b 0' in text
    # 패키지 목록이 바뀐 때만 다시 받는다 — git blob id로 비교(작업 폴더 줄바꿈과 무관)
    assert "rev-parse HEAD:scripts/onprem-requirements.txt" in text and "REQ_BLOB" in text
    assert "--branch runtime-win64" in text and "--depth 1" in text
    # 미완성 runtime 폴더를 지우지는 않는다(사용자 파일일 수 있음)
    assert "rmdir" not in text and "rd /s" not in text.lower()


def test_runtime_folder_is_ignored_in_main():
    assert "runtime/" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


def test_build_scripts_share_one_runtime_builder():
    runtime = _read("packaging/build_runtime.ps1")
    assert 'git rev-parse "HEAD:scripts/onprem-requirements.txt"' in runtime and "REQ_BLOB" in runtime
    assert "BUILD.txt" in runtime and "Lib\\site-packages" in runtime
    bundle = _read("packaging/build_windows_bundle.ps1")
    assert "build_runtime.ps1" in bundle and "python.org/ftp" not in bundle        # 두 벌로 갈라지지 않는다


def test_ci_builds_runtime_branch_and_checks_fresh_clone():
    wf = yaml.safe_load((ROOT / ".github/workflows/windows.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    assert {"runtime-branch", "git-install-check"} <= set(jobs)
    assert jobs["runtime-branch"]["needs"] == ["lock-sync", "test"]                 # 깨진 코드의 runtime을 올리지 않는다
    assert jobs["git-install-check"]["needs"] == "runtime-branch"
    publish = "\n".join(str(step.get("run", "")) for step in jobs["runtime-branch"]["steps"])
    assert "git push --force origin runtime-win64" in publish and "--orphan" in publish
    check = "\n".join(str(step.get("run", "")) for step in jobs["git-install-check"]["steps"])
    assert "git clone" in check and "--branch" in check and "ensure_runtime.bat" in check and "Downloading" in check


def _doctor_root(tmp_path, monkeypatch, stamp: str | None, want: str):
    (tmp_path / ".git").mkdir(exist_ok=True)
    if stamp is not None:
        (tmp_path / "runtime").mkdir(exist_ok=True)
        (tmp_path / "runtime" / "REQ_BLOB").write_text(stamp, encoding="ascii")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)

    class Done:
        stdout = want + "\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Done())


def test_doctor_runtime_matches_requirements(tmp_path, monkeypatch):
    _doctor_root(tmp_path, monkeypatch, "abc1234567890", "abc1234567890")
    checks = doctor._runtime()
    assert [c.level for c in checks] == [OK]


def test_doctor_warns_when_runtime_is_older_than_code(tmp_path, monkeypatch):
    _doctor_root(tmp_path, monkeypatch, "abc1234567890", "def9876543210")
    (check,) = doctor._runtime()
    assert check.level == WARN and "start_webapp.bat" in check.fix


def test_doctor_runtime_check_is_silent_without_stamp_or_git(tmp_path, monkeypatch):
    _doctor_root(tmp_path, monkeypatch, None, "x")
    assert doctor._runtime() == []                                                  # 설치 묶음·uv 환경에는 해당 없음
    _doctor_root(tmp_path, monkeypatch, "abc", "")                                  # git이 값을 못 줌
    assert [c.level for c in doctor._runtime()] == [INFO]
