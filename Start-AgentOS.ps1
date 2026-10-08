param([int]$Port = 8000, [switch]$SetupSample, [switch]$Build, [switch]$Demo)
$ErrorActionPreference = 'Stop'
if ($Demo -and $SetupSample) { throw 'Demo selects its sample without changing workspace configuration. Omit -SetupSample.' }
Set-Location -LiteralPath $PSScriptRoot
$agentosPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv-runtime\Scripts\python.exe')) {
    $agentosPython = Join-Path $PSScriptRoot '.venv-runtime\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $agentosPython)) { throw 'Install backend dependencies in .venv first. See docs/getting-started.md.' }
if ($Build -or -not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
    npm --prefix frontend ci --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
if ($SetupSample) {
    & $agentosPython -m agentos setup-sample
    if ($LASTEXITCODE -ne 0) { throw 'Sample setup failed; existing configuration was preserved.' }
}
$agentosArguments = @('-m', 'agentos', 'serve', '--port', "$Port")
if ($Demo) { $agentosArguments += '--demo' }
& $agentosPython @agentosArguments
if ($LASTEXITCODE -ne 0) { throw 'AgentOS exited with an error.' }
