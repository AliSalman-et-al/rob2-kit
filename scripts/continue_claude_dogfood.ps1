param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$RunId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Label,

    [Parameter(Mandatory = $true)]
    [string]$SessionId,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Prompt
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runRoot = Join-Path $repoRoot (Join-Path 'eval/runs' $RunId)
$manifestPath = Join-Path $runRoot 'run-manifest.json'
$configPath = Join-Path $runRoot 'run-config.json'
$mcpConfigPath = Join-Path $runRoot 'mcp-config.json'

foreach ($path in @($runRoot, $manifestPath, $configPath, $mcpConfigPath)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing run artifact: $path" }
}

$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
$workspaceRoot = [string]$config.workspace
$streamPath = Join-Path $runRoot "$Label-stream.jsonl"
$stderrPath = Join-Path $runRoot "$Label-stderr.log"
$heartbeatPath = Join-Path $runRoot "$Label-heartbeat.jsonl"
foreach ($path in @($streamPath, $stderrPath, $heartbeatPath)) {
    if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite continuation artifact: $path" }
}

$claudeArgs = @(
    '-p', $Prompt,
    '--resume', $SessionId,
    '--model', 'haiku',
    '--autocompact', '100k',
    '--permission-mode', 'bypassPermissions',
    '--setting-sources', 'project',
    '--strict-mcp-config',
    '--mcp-config', $mcpConfigPath,
    '--output-format', 'stream-json',
    '--verbose',
    '--tools', 'Read,ToolSearch',
    '--allowedTools', 'Read,ToolSearch,mcp__rob2__*'
)
$quotedArgs = @($claudeArgs | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' })
$started = [DateTime]::UtcNow
$process = Start-Process -FilePath 'claude.exe' -ArgumentList ($quotedArgs -join ' ') `
    -WorkingDirectory $workspaceRoot -RedirectStandardOutput $streamPath `
    -RedirectStandardError $stderrPath -PassThru -NoNewWindow
try {
    while (-not $process.HasExited) {
        $streamInfo = Get-Item -LiteralPath $streamPath -ErrorAction SilentlyContinue
        $state = Get-ChildItem -LiteralPath (Join-Path $workspaceRoot '.rob2-kit') `
            -File -Recurse -ErrorAction SilentlyContinue
        $measure = $state | Measure-Object -Property Length -Sum
        $stateBytes = if ($null -eq $measure.Sum) { 0 } else { [long]$measure.Sum }
        [ordered]@{
            timestamp = [DateTime]::UtcNow.ToString('o')
            pid = $process.Id
            stream_bytes = if ($null -ne $streamInfo) { $streamInfo.Length } else { 0 }
            stream_last_write = if ($null -ne $streamInfo) {
                $streamInfo.LastWriteTimeUtc.ToString('o')
            } else { $null }
            rob2_state_present = ($null -ne $state)
            rob2_state_bytes = $stateBytes
        } | ConvertTo-Json -Compress | Add-Content -LiteralPath $heartbeatPath -Encoding utf8
        Start-Sleep -Seconds 5
    }
    $process.WaitForExit()
    $claudeExit = $process.ExitCode
} finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

$result = $null
foreach ($line in Get-Content -LiteralPath $streamPath) {
    try { $event = $line | ConvertFrom-Json } catch { continue }
    if ($event.type -eq 'result') { $result = $event }
}

$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$sessions = @($manifest.sessions)
$sessions += [ordered]@{
    label = $Label
    session_id = if ($null -ne $result) { $result.session_id } else { $SessionId }
    prompt = $Prompt
    started_at = $started.ToString('o')
    finished_at = [DateTime]::UtcNow.ToString('o')
    exit_code = $claudeExit
    stream = "$Label-stream.jsonl"
    stderr = "$Label-stderr.log"
    heartbeat = "$Label-heartbeat.jsonl"
}
$manifest.sessions = $sessions
$manifest.terminal_status = if ($null -eq $result) {
    'no_result'
} elseif ($result.is_error) {
    'blocked'
} else {
    $result.subtype
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding utf8

Write-Output "Run root: $runRoot"
Write-Output "Continuation: $Label"
Write-Output "Exit: $claudeExit"
