$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    & python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the virtual environment.' }
}
& $projectPython -m pip install -e ($projectRoot + '[dev]')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $envPath
}
Write-Output 'Setup complete. Run .\.venv\Scripts\python.exe -m personal_mcp doctor'
