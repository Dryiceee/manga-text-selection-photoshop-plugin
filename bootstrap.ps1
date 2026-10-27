param([ValidateSet('deploy', 'check', 'prepare', 'install')][string]$Mode = 'deploy')
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$runtime = $null
$candidates = @()
if ($env:MANGA_PYTHON_EXE) { $candidates += [pscustomobject]@{Exe=$env:MANGA_PYTHON_EXE;Args=@()} }
$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) { $candidates += [pscustomobject]@{Exe=$launcher.Source;Args=@('-3.12')} }
$plainPython = Get-Command python.exe -ErrorAction SilentlyContinue
if ($plainPython -and $plainPython.Source -notmatch '\\Microsoft\\WindowsApps\\python.exe$') {
    $candidates += [pscustomobject]@{Exe=$plainPython.Source;Args=@()}
}
foreach ($candidate in $candidates) {
    try {
        $arguments = @($candidate.Args) + @('-c', "import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8; print(sys.executable)")
        $found = & $candidate.Exe @arguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { $runtime = [string](@($found)[-1]); break }
    } catch { continue }
}
if (-not $runtime) {
    Write-Host 'Python 3.12 x64 was not found. See the tutorial in this folder.'
    Write-Host 'Official download: https://www.python.org/downloads/'
    Write-Host 'With the official Python install manager: py install 3.12'
    Write-Host 'For an agent-managed runtime, set MANGA_PYTHON_EXE to its python.exe path.'
    exit 1
}
& $runtime -u (Join-Path $PSScriptRoot 'deploy.py') $Mode
exit $LASTEXITCODE
