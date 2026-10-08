param([ValidateRange(1, 65535)][int]$Port = 8000, [switch]$Demo)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$agentosElectron = Join-Path $PSScriptRoot 'desktop\node_modules\electron\dist\electron.exe'
if (-not (Test-Path -LiteralPath $agentosElectron)) { throw 'Install desktop dependencies and runtime: npm --prefix desktop ci; npm --prefix desktop run install:runtime. See docs/desktop.md.' }
if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) { throw 'Build the client: npm --prefix frontend run build.' }
$agentosDesktopArguments = @((Join-Path $PSScriptRoot 'desktop'), '--root', $PSScriptRoot, '--port', "$Port")
if ($Demo) { $agentosDesktopArguments += '--demo' }
$agentosRunAsNodePresent = Test-Path Env:ELECTRON_RUN_AS_NODE
$agentosRunAsNodeValue = $env:ELECTRON_RUN_AS_NODE
try {
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    & $agentosElectron @agentosDesktopArguments
    if ($LASTEXITCODE -ne 0) { throw 'AgentOS desktop exited with an error.' }
} finally {
    if ($agentosRunAsNodePresent) { $env:ELECTRON_RUN_AS_NODE = $agentosRunAsNodeValue }
    else { Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue }
}
