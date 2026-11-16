$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Error "尚未安装：请先运行 .\setup.ps1。"
    exit 1
}
& $pythonPath (Join-Path $PSScriptRoot "transcribe.py") @args
exit $LASTEXITCODE
