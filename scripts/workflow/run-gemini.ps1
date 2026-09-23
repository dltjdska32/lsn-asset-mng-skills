param(
    [Parameter(Mandatory=$true)][string]$WorkingDirectory,
    [Parameter(Mandatory=$true)][string]$PromptFile,
    [Parameter(Mandatory=$true)][string]$RunId,
    [Parameter(Mandatory=$true)][string]$ConversationId
)
$ErrorActionPreference = 'Stop'
if ($RunId -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid run id' }
$taskDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
$taskPrompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding utf8
$taskOutput = Join-Path $taskDirectory 'workspace/runs'
New-Item -ItemType Directory -Force -Path $taskOutput | Out-Null
$taskReceipt = [ordered]@{
    task = $RunId; model = 'gemini-3.8-flash-high'; effort = 'high'
    conversation = $ConversationId; worktree = $taskDirectory
    startedUtc = [DateTime]::UtcNow.ToString('o'); endedUtc = $null
    supervisorPid = $PID; baseCommit = $null; exitCode = $null
}
Push-Location -LiteralPath $taskDirectory
try {
    $taskReceipt.baseCommit = (git rev-parse HEAD)
    $taskReceipt | ConvertTo-Json | Set-Content -LiteralPath "$taskOutput/$RunId.receipt.json" -Encoding utf8
    & 'C:/Users/lsn/AppData/Local/agy/bin/agy.exe' --model gemini-3.8-flash-high --effort high --mode accept-edits --conversation $ConversationId --output-format json --log-file "$taskOutput/$RunId.log" --print $taskPrompt > "$taskOutput/$RunId.json"
    $taskExitCode = $LASTEXITCODE
    $taskReceipt.exitCode = $taskExitCode
} finally {
    $taskReceipt.endedUtc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt | ConvertTo-Json | Set-Content -LiteralPath "$taskOutput/$RunId.receipt.json" -Encoding utf8
    Pop-Location
}
exit $taskExitCode
