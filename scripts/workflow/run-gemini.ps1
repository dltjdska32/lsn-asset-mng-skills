param(
    [Parameter(Mandatory=$true)][string]$WorkingDirectory,
    [Parameter(Mandatory=$true)][string]$PromptFile,
    [Parameter(Mandatory=$true)][string]$RunId,
    [Parameter(Mandatory=$true)][string]$ConversationId,
    [string]$Model = 'gemini-3.1-pro-high'
)
$ErrorActionPreference = 'Stop'
if ($RunId -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid run id' }
if ($Model -notmatch '^gemini-[a-z0-9.-]+$') { throw 'Invalid Gemini model id' }
$taskDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
$taskPrompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding utf8
$taskOutput = Join-Path $taskDirectory 'workspace/runs'
New-Item -ItemType Directory -Force -Path $taskOutput | Out-Null
$taskReceipt = [ordered]@{
    task = $RunId; model = $Model; effort = 'high'
    conversation = $ConversationId; worktree = $taskDirectory
    startedUtc = [DateTime]::UtcNow.ToString('o'); endedUtc = $null
    supervisorPid = $PID; baseCommit = $null; exitCode = $null
}
Push-Location -LiteralPath $taskDirectory
try {
    $taskReceipt.baseCommit = (git rev-parse HEAD)
    $taskPrompt = "Execution assignment: $RunId. Verified base commit: $($taskReceipt.baseCommit). Assigned worktree: $taskDirectory. This exact base supersedes any placeholder base in the assignment. Headless mode cannot approve RunCommand: never invoke command, shell, terminal, git, tests, package installers, or web tools. Use file read/write tools only inside this assigned worktree. The coordinator runs git and tests. Record this base and any requested test commands in the handoff without running them.`n`n" + $taskPrompt
    $taskReceipt | ConvertTo-Json | Set-Content -LiteralPath "$taskOutput/$RunId.receipt.json" -Encoding utf8
    & 'C:/Users/lsn/AppData/Local/agy/bin/agy.exe' --model $Model --effort high --mode accept-edits --conversation $ConversationId --output-format json --log-file "$taskOutput/$RunId.log" --print $taskPrompt > "$taskOutput/$RunId.json"
    $taskExitCode = $LASTEXITCODE
    if ($taskExitCode -eq 0) {
        $taskResult = Get-Content -LiteralPath "$taskOutput/$RunId.json" -Raw | ConvertFrom-Json
        $taskReceipt['providerStatus'] = $taskResult.status
        $taskReceipt['deniedActionCount'] = @($taskResult.denied_actions | Where-Object { $null -ne $_ }).Count
        $taskReceipt['responseCharacters'] = ([string]$taskResult.response).Length
        if ($taskResult.status -ne 'SUCCESS' -or $taskReceipt.deniedActionCount -gt 0 -or $taskReceipt.responseCharacters -eq 0) {
            $taskExitCode = 2
        }
    }
    $taskReceipt.exitCode = $taskExitCode
} finally {
    $taskReceipt.endedUtc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt | ConvertTo-Json | Set-Content -LiteralPath "$taskOutput/$RunId.receipt.json" -Encoding utf8
    Pop-Location
}
exit $taskExitCode
