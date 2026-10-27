$ErrorActionPreference = 'Stop'
$pidPath = Join-Path $PSScriptRoot 'server.pid'
if (-not (Test-Path -LiteralPath $pidPath)) { exit }
$serverProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
$serverProcess = Get-Process -Id $serverProcessId -ErrorAction SilentlyContinue
if (-not $serverProcess) { exit }
$venvConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot '.venv\pyvenv.cfg')
$basePythonHome = ($venvConfig | Where-Object { $_ -match '^home = ' }) -replace '^home = ', ''
$expectedPythonPaths = @((Join-Path $PSScriptRoot '.venv\Scripts\python.exe'), (Join-Path $basePythonHome 'python.exe'))
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $serverProcessId"
$expectedScript = Join-Path $PSScriptRoot 'app.py'
$usesScript = $processInfo.CommandLine.Contains($expectedScript) -or $processInfo.CommandLine -match '(?:^|\s)-u\s+"?app\.py"?\s*$'
$startDelta = ((Get-Item -LiteralPath $pidPath).LastWriteTime - $serverProcess.StartTime).TotalSeconds
if ($serverProcess.Path -in $expectedPythonPaths -and $usesScript -and $startDelta -ge 0 -and $startDelta -lt 120) {
    Stop-Process -Id $serverProcessId -ErrorAction Stop
    $null = $serverProcess.WaitForExit(5000)
} else {
    throw '进程身份不匹配，未停止其他程序。'
}
