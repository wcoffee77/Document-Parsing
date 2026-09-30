# doc2report 설치 묶음(zip) 만들기 — 인터넷이 되는 Windows(보통 GitHub Actions)에서 실행한다.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows_bundle.ps1
#
# 결과: dist\doc2report-windows-x64.zip
#   doc2report\
#     start_webapp.bat, doctor.bat, src\, profiles\, rules\, docs\, scripts\ ...  (git이 추적하는 파일만)
#     runtime\   python.org 공식 embeddable 파이썬 + 필요한 패키지 전부(Lib\site-packages)
#
# 왜 이렇게 만드나(2026-09-30 사용자): 사내 PC는 pypi.org·astral.sh가 막혀 파이썬·uv·패키지 설치에서
# 시간을 많이 썼다. 받는 사람은 zip을 풀고 start_webapp.bat을 두 번 누르기만 하면 되게 — 설치·관리자
# 권한·인터넷·PowerShell 실행 정책 모두 필요 없게 한다. 파이썬은 서명된 python.org 공식 파일을 쓴다
# (사내 보안 프로그램이 서명 없는 실행 파일을 막는 경우 대비). 패키지 버전은 uv.lock에서 뽑은
# scripts\onprem-requirements.txt 그대로(개발 환경과 똑같은 버전).
#
# 빌드하는 PC의 파이썬 버전(예: 3.13.x)과 같은 버전의 embeddable을 받는다 — 패키지(wheel)의 ABI가 맞아야 한다.

param([string]$OutDir = "dist")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pyver = (python -c "import platform; print(platform.python_version())").Trim()
$tag = (python -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')").Trim()
$arch = (python -c "import platform; print(platform.machine())").Trim()
if ($arch -ne "AMD64") { throw "64비트(AMD64) 파이썬으로 빌드하세요 (지금: $arch)" }
Write-Host "파이썬 $pyver 기준으로 묶음을 만듭니다"

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
$stage = Join-Path $root "$OutDir\doc2report"
New-Item -ItemType Directory -Force $stage | Out-Null

# 1) 앱 파일 — git이 추적하는 파일만(개인 토큰 스크립트·결과 폴더·가상환경이 섞이지 않게)
git archive --format=zip -o "$OutDir\app.zip" HEAD
Expand-Archive "$OutDir\app.zip" $stage
Remove-Item "$OutDir\app.zip"
foreach ($drop in @("tests", ".github", "tools", "packaging", "uv.lock", ".gitignore", ".gitattributes")) {
    $path = Join-Path $stage $drop
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

# 2) 파이썬 — python.org 공식 embeddable(설치 없이 폴더째 쓰는 배포판)
$embed = "python-$pyver-embed-amd64.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$pyver/$embed" -OutFile "$OutDir\$embed"
Expand-Archive "$OutDir\$embed" "$stage\runtime"
Remove-Item "$OutDir\$embed"
# ._pth가 모듈 검색 경로를 정한다: 표준 라이브러리 zip, 패키지, 그리고 앱 소스(..\src)
Set-Content -Encoding ascii "$stage\runtime\python$tag._pth" -Value @(
    "python$tag.zip", ".", "Lib\site-packages", "..\src", "import site")

# 3) 패키지 — uv.lock과 같은 버전을 Windows용 바이너리(wheel)로만
python -m pip install --disable-pip-version-check --no-deps --only-binary=:all: --no-compile `
    --target "$stage\runtime\Lib\site-packages" -r scripts\onprem-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "패키지 설치 실패" }

# 4) 빌드 정보 — doctor가 보여 준다
$commit = (git rev-parse --short HEAD).Trim()
Set-Content -Encoding utf8 "$stage\runtime\BUILD.txt" -Value @(
    "commit $commit", "built $(Get-Date -Format 'yyyy-MM-dd HH:mm')", "python $pyver")

# 5) 압축
$zip = Join-Path $root "$OutDir\doc2report-windows-x64.zip"
Compress-Archive -Path $stage -DestinationPath $zip
Write-Host ("완료: {0} ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
