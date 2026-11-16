param([switch]$Whisper, [string]$Python = "")
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        throw "缺少 ffmpeg：运行 winget install Gyan.FFmpeg，重开 PowerShell 后再试。"
    }
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        if ($Python) {
            & $Python -c 'import sys; sys.exit(not (3,10) <= sys.version_info[:2] <= (3,12))'
            if ($LASTEXITCODE -ne 0) { throw "请指定 Python 3.10–3.12。" }
            & $Python -m venv .venv
        } else {
            $selected = $false
            if (Get-Command py -ErrorAction SilentlyContinue) {
                foreach ($version in @("-3.11", "-3.12", "-3.10")) {
                    & py $version -c 'import sys; sys.exit(not (3,10) <= sys.version_info[:2] <= (3,12))' 2>$null
                    if ($LASTEXITCODE -eq 0) {
                        & py $version -m venv .venv
                        $selected = $true
                        break
                    }
                }
            }
            if (-not $selected) { throw "需要 Python 3.11。可用 uv venv --python 3.11 .venv 后重跑，或用 -Python 指定 python.exe。" }
        }
        if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败，请查看上方错误。" }
    }
    $installArgs = @("setup_install.py")
    if ($Whisper) { $installArgs += "--whisper" }
    & ".venv\Scripts\python.exe" @installArgs
    if ($LASTEXITCODE -ne 0) { throw "安装未完成，请查看上方错误。" }
} finally {
    Pop-Location
}
