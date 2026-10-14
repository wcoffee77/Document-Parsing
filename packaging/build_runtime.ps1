# doc2report 실행 환경(runtime) 만들기 — 인터넷이 되는 Windows(보통 GitHub Actions)에서 실행한다.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_runtime.ps1 -Target dist\runtime
#
# 결과: -Target 폴더에 python.org 공식 embeddable 파이썬 + 필요한 패키지 전부(Lib\site-packages) + BUILD.txt + REQ_BLOB.
# 두 곳에서 쓴다: ① 설치 묶음 zip(build_windows_bundle.ps1) ② git의 runtime-win64 브랜치(CI가 올림 — 받은 사람은
# start_webapp.bat이 첫 실행 때 자동으로 받는다, scripts\ensure_runtime.bat).
#
# REQ_BLOB = 패키지 목록(scripts/onprem-requirements.txt)의 **git blob id**. 파일 해시 대신 이것을 쓰는 이유: 받은 PC의
# 작업 폴더는 줄바꿈이 CRLF일 수 있어 파일 해시가 CI와 달라지지만, git이 계산하는 blob id는 줄바꿈 설정과 무관하게 같다.
#
# 빌드하는 PC의 파이썬 버전(예: 3.13.x)과 같은 버전의 embeddable을 받는다 — 패키지(wheel)의 ABI가 맞아야 한다.

param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$WorkDir = "dist"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pyver = (python -c "import platform; print(platform.python_version())").Trim()
$tag = (python -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')").Trim()
$arch = (python -c "import platform; print(platform.machine())").Trim()
if ($arch -ne "AMD64") { throw "64비트(AMD64) 파이썬으로 빌드하세요 (지금: $arch)" }
Write-Host "파이썬 $pyver 기준으로 runtime을 만듭니다"

New-Item -ItemType Directory -Force $WorkDir | Out-Null
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }

# 1) 파이썬 — python.org 공식 embeddable(설치 없이 폴더째 쓰는 배포판, 서명된 python.exe)
$embed = "python-$pyver-embed-amd64.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$pyver/$embed" -OutFile "$WorkDir\$embed"
Expand-Archive "$WorkDir\$embed" $Target
Remove-Item "$WorkDir\$embed"
# ._pth가 모듈 검색 경로를 정한다: 표준 라이브러리 zip, 패키지, 그리고 앱 소스(..\src)
Set-Content -Encoding ascii "$Target\python$tag._pth" -Value @(
    "python$tag.zip", ".", "Lib\site-packages", "..\src", "import site")

# 2) 패키지 — uv.lock과 같은 버전을 Windows용 바이너리(wheel)로만
python -m pip install --disable-pip-version-check --no-deps --only-binary=:all: --no-compile `
    --target "$Target\Lib\site-packages" -r scripts\onprem-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "패키지 설치 실패" }

# 3) 빌드 정보 — doctor가 보여 주고, start_webapp.bat이 패키지 목록이 바뀌었는지 비교한다
$commit = (git rev-parse --short HEAD).Trim()
$blob = (git rev-parse "HEAD:scripts/onprem-requirements.txt").Trim()
Set-Content -Encoding utf8 "$Target\BUILD.txt" -Value @(
    "commit $commit", "built $(Get-Date -Format 'yyyy-MM-dd HH:mm')", "python $pyver")
Set-Content -Encoding ascii -NoNewline "$Target\REQ_BLOB" -Value $blob
Write-Host "runtime 완료: $Target (REQ_BLOB $blob)"
