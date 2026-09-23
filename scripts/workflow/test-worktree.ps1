param(
    [Parameter(Mandatory=$true)][string]$WorkingDirectory,
    [Parameter(Mandatory=$true)][string]$RunId,
    [string]$Pattern = 'test*.py'
)
$ErrorActionPreference = 'Stop'
if ($RunId -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid run id' }
$taskDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
$taskPython = 'C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe'
$taskOutput = Join-Path $taskDirectory 'workspace/runs'
New-Item -ItemType Directory -Force -Path $taskOutput | Out-Null
$taskPreviousPath = $env:PYTHONPATH
$taskReceipt = [ordered]@{ task=$RunId; worktree=$taskDirectory; pattern=$Pattern; startedUtc=[DateTime]::UtcNow.ToString('o'); endedUtc=$null; baseCommit=$null; exitCode=$null }
Push-Location -LiteralPath $taskDirectory
try {
    $env:PYTHONPATH = Join-Path $taskDirectory 'runtime'
    $taskReceipt.baseCommit = (git -c "safe.directory=$taskDirectory" rev-parse HEAD)
    $taskImportPath = (& $taskPython -X utf8 -B -c 'import investment_stack; print(investment_stack.__file__)')
    if ($LASTEXITCODE -ne 0 -or -not [string]$taskImportPath -or -not $taskImportPath.StartsWith($env:PYTHONPATH, [StringComparison]::OrdinalIgnoreCase)) { throw "Tests did not import the requested worktree: $taskImportPath" }
    $taskReceipt['importPath'] = $taskImportPath
    & $taskPython -X utf8 -B -m unittest discover -s tests -p $Pattern -q 2>&1 | Tee-Object -FilePath "$taskOutput/$RunId.tests.log"
    $taskExitCode = $LASTEXITCODE
    $taskReceipt.exitCode = $taskExitCode
} finally {
    $taskReceipt.endedUtc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt | ConvertTo-Json | Set-Content -LiteralPath "$taskOutput/$RunId.tests.receipt.json" -Encoding utf8
    $env:PYTHONPATH = $taskPreviousPath
    Pop-Location
}
exit $taskExitCode
