# doc2report 웹 화면 켜기 (Windows PowerShell)
#
#   더블클릭: 저장소 맨 위의 start_webapp.bat
#   직접:     powershell -ExecutionPolicy Bypass -File scripts\start_webapp.ps1 [--port 8800] [--output-dir D:\보고서]
#
# scripts\confluence_env.ps1(Confluence 토큰)과 scripts\onprem_env.ps1(온프렘 LLM)이 있으면
# 먼저 불러온 뒤 서버를 띄운다 — PowerShell 창마다 ". .\scripts\..."를 다시 칠 필요가 없다.
# 팀원은 이 스크립트 없이 웹 화면의 '사용자 등록'으로 각자 토큰을 넣는다(등록 정보가 있으면 그쪽이 우선).
# 서버는 이 PC(127.0.0.1)에서만 접속된다. 끄려면 이 창에서 Ctrl+C.
# (이 파일은 한글이 깨지지 않도록 UTF-8 BOM으로 저장해 둔다 — Windows PowerShell 5.1)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

foreach ($name in @("confluence_env.ps1", "onprem_env.ps1")) {
    $path = Join-Path $PSScriptRoot $name
    if (Test-Path $path) {
        . $path
        Write-Host "환경 설정 불러옴: scripts\$name"
    }
}

$uv = if (Test-Path (Join-Path $root "uv.exe")) { Join-Path $root "uv.exe" } else { "uv" }
if (-not (Get-Command $uv -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "[설치 필요] 파이썬 실행 환경을 찾지 못했습니다." -ForegroundColor Yellow
    Write-Host "  가장 쉬운 방법: 설치 묶음 zip(doc2report-windows-x64.zip)의 runtime 폴더를 이 폴더에 복사하세요."
    Write-Host "  자세한 방법: docs\team-setup.md"
    exit 1
}
if ($args.Count -gt 0 -and $args[0] -eq "--doctor") {
    & $uv run --offline --no-sync doc2report doctor --save
} else {
    & $uv run --offline --no-sync doc2report web @args
}
