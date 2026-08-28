param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$RunId,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RequestedOutcome,

    [Parameter(Mandatory = $true)]
    [ValidateCount(1, 100)]
    [ValidateNotNullOrEmpty()]
    [string[]]$TrialNames
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runRoot = Join-Path $repoRoot (Join-Path 'eval/runs' $RunId)
$workspaceRoot = Join-Path $runRoot 'workspace'

if (Test-Path -LiteralPath $runRoot) { throw "Refusing to overwrite existing run: $runRoot" }
if (Test-Path -LiteralPath $workspaceRoot) { throw "Refusing to overwrite existing workspace: $workspaceRoot" }

$sourceRoot = Join-Path $repoRoot 'eval/reference/sources'
$inputRoot = Join-Path $workspaceRoot 'input'
$wheelRoot = Join-Path $runRoot 'wheel'
$runtimeRoot = Join-Path $runRoot 'runtime'
$mcpConfigPath = Join-Path $runRoot 'mcp-config.json'
$runConfigPath = Join-Path $runRoot 'run-config.json'
$manifestPath = Join-Path $runRoot 'run-manifest.json'

New-Item -ItemType Directory -Force -Path $runRoot, $workspaceRoot, $inputRoot, $wheelRoot | Out-Null
try {
    Set-Content -LiteralPath (Join-Path $runRoot 'workspace-path.txt') -Value "$workspaceRoot`r`nThe live ROB2 state is in $workspaceRoot\.rob2-kit." -Encoding utf8
    foreach ($trialName in $trialNames) {
        $sourceTrial = Join-Path $sourceRoot $trialName
        if (-not (Test-Path -LiteralPath $sourceTrial -PathType Container)) { throw "Missing source trial: $trialName" }
        Copy-Item -LiteralPath $sourceTrial -Destination (Join-Path $inputRoot $trialName) -Recurse -Force
    }

    & uv build --wheel --out-dir $wheelRoot
    if ($LASTEXITCODE -ne 0) { throw "uv build failed with exit code $LASTEXITCODE" }
    $wheel = @(Get-ChildItem -LiteralPath $wheelRoot -Filter '*.whl' -File)
    if ($wheel.Count -ne 1) { throw "Expected one wheel, found $($wheel.Count)" }

    & uv venv $runtimeRoot
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed with exit code $LASTEXITCODE" }
    $runtimePython = Join-Path $runtimeRoot 'Scripts/python.exe'
    & uv pip install --python $runtimePython $wheel[0].FullName
    if ($LASTEXITCODE -ne 0) { throw "uv pip install failed with exit code $LASTEXITCODE" }

    $rob2Exe = Join-Path $runtimeRoot 'Scripts/rob2.exe'
    $workspaceSkillTarget = Join-Path $workspaceRoot '.claude/skills/rob2-assess'
    & $rob2Exe export-skill --output $workspaceSkillTarget
    if ($LASTEXITCODE -ne 0) { throw "rob2 export-skill failed with exit code $LASTEXITCODE" }
    $mcpConfig = [ordered]@{
        mcpServers = [ordered]@{
            rob2 = [ordered]@{
                command = $rob2Exe
                args = @('mcp')
                env = [ordered]@{ ROB2_WORKSPACE = $workspaceRoot }
            }
        }
    }
    $mcpConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $mcpConfigPath -Encoding utf8

    $trialPrompt = if ($TrialNames.Count -eq 1) {
        $TrialNames[0]
    } elseif ($TrialNames.Count -eq 2) {
        "$($TrialNames[0]) and $($TrialNames[1])"
    } else {
        "$($TrialNames[0..($TrialNames.Count - 2)] -join ', '), and $($TrialNames[-1])"
    }
    $prompt = "/rob2-assess Assess risk of bias for $RequestedOutcome across $trialPrompt in input."
    $allowedTools = @('Read', 'ToolSearch', 'mcp__rob2__*')
    $toolNames = @(
        'mcp__rob2__prepare_batch', 'mcp__rob2__get_status', 'mcp__rob2__list_sources',
        'mcp__rob2__search_sources', 'mcp__rob2__read_pages', 'mcp__rob2__select_text_evidence',
        'mcp__rob2__render_page', 'mcp__rob2__select_visual_evidence', 'mcp__rob2__save_proposal',
        'mcp__rob2__request_proposal_approval', 'mcp__rob2__get_domain_context',
        'mcp__rob2__save_domain_judgment',
        'mcp__rob2__request_trial_terminal', 'mcp__rob2__finalize_batch'
    )
    $runConfig = [ordered]@{
        model = 'haiku'
        permission_mode = 'bypassPermissions'
        strict_mcp_config = $true
        autocompact = '100k'
        output_format = 'stream-json'
        verbose = $true
        builtin_tools = @('Read', 'ToolSearch')
        allowed_tools = $allowedTools
        mcp_tools_exactly = $toolNames
        prompt = $prompt
        mcp_config = 'mcp-config.json'
        workspace = $workspaceRoot
        workspace_path_file = 'workspace-path.txt'
        source_trials = $trialNames
        source_root = 'eval/reference/sources'
    }
    $runConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $runConfigPath -Encoding utf8

    $sourceHashes = [ordered]@{}
    foreach ($trialName in $trialNames) {
        $files = [ordered]@{}
        foreach ($file in Get-ChildItem -LiteralPath (Join-Path $inputRoot $trialName) -File -Recurse) {
            $relative = $file.FullName.Substring((Join-Path $inputRoot $trialName).Length + 1)
            $files[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $sourceHashes[$trialName] = $files
    }
    $manifest = [ordered]@{
        run_id = $RunId
        started_at = [DateTime]::UtcNow.ToString('o')
        commit = (& git rev-parse HEAD).Trim()
        prompt = $prompt
        command_shape = [ordered]@{
            executable = 'claude'
            arguments = @('-p', '<prompt>', '--model', 'haiku', '--autocompact', '100k', '--permission-mode', 'bypassPermissions', '--setting-sources', 'project', '--strict-mcp-config', '--mcp-config', 'mcp-config.json', '--output-format', 'stream-json', '--verbose', '--tools', 'Read,ToolSearch', '--allowedTools', 'Read,ToolSearch,mcp__rob2__*')
            working_directory = $workspaceRoot
        }
        runtime = $runtimeRoot
        workspace = $workspaceRoot
        wheel = $wheel[0].FullName
        wheel_sha256 = (Get-FileHash -LiteralPath $wheel[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        source_hashes = $sourceHashes
        sessions = @()
        host_init = $null
        terminal_status = 'initializing'
    }
    $manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding utf8

    $oldClaudeConfig = $env:CLAUDE_CONFIG_DIR
    Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue
    $streamPath = Join-Path $runRoot 'initial-stream.jsonl'
    $stderrPath = Join-Path $runRoot 'initial-stderr.log'
    $heartbeatPath = Join-Path $runRoot 'initial-heartbeat.jsonl'
    $claudeArgs = @(
        '-p', $prompt,
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
    $started = [DateTime]::UtcNow
    $quotedArgs = @($claudeArgs | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' })
    $argumentLine = $quotedArgs -join ' '
    $process = $null
    try {
        $process = Start-Process -FilePath 'claude.exe' -ArgumentList $argumentLine -WorkingDirectory $workspaceRoot -RedirectStandardOutput $streamPath -RedirectStandardError $stderrPath -PassThru -NoNewWindow
        while (-not $process.HasExited) {
            $streamInfo = Get-Item -LiteralPath $streamPath -ErrorAction SilentlyContinue
            $state = Get-ChildItem -LiteralPath (Join-Path $workspaceRoot '.rob2-kit') -File -Recurse -ErrorAction SilentlyContinue
            $measure = $state | Measure-Object -Property Length -Sum
            $stateBytes = if ($null -eq $measure -or $null -eq $measure.Sum) { 0 } else { [long]$measure.Sum }
            [ordered]@{
                timestamp = [DateTime]::UtcNow.ToString('o')
                pid = $process.Id
                stream_bytes = if ($null -ne $streamInfo) { $streamInfo.Length } else { 0 }
                stream_last_write = if ($null -ne $streamInfo) { $streamInfo.LastWriteTimeUtc.ToString('o') } else { $null }
                rob2_state_present = ($null -ne $state)
                rob2_state_bytes = $stateBytes
            } | ConvertTo-Json -Compress | Add-Content -LiteralPath $heartbeatPath -Encoding utf8
            Start-Sleep -Seconds 5
        }
        $process.WaitForExit()
        $claudeExit = $process.ExitCode
    } finally {
        if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    }
    if ($null -eq $oldClaudeConfig) { Remove-Item Env:CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue } else { $env:CLAUDE_CONFIG_DIR = $oldClaudeConfig }

    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $result = $null
    foreach ($line in Get-Content -LiteralPath $streamPath) {
        try { $event = $line | ConvertFrom-Json } catch { continue }
        if ($event.type -eq 'result') { $result = $event }
    }
    $manifest.sessions = @([ordered]@{
        label = 'initial'
        session_id = if ($null -ne $result) { $result.session_id } else { $null }
        prompt = $prompt
        started_at = $started.ToString('o')
        finished_at = [DateTime]::UtcNow.ToString('o')
        exit_code = $claudeExit
        stream = 'initial-stream.jsonl'
        stderr = 'initial-stderr.log'
        heartbeat = 'initial-heartbeat.jsonl'
    })
    $init = $null
    foreach ($line in Get-Content -LiteralPath $streamPath) {
        try { $event = $line | ConvertFrom-Json } catch { continue }
        if ($event.type -eq 'system' -and $event.subtype -eq 'init') { $init = $event; break }
    }
    $manifest.host_init = if ($null -ne $init) {
        [ordered]@{
            cwd = $init.cwd
            tools = @($init.tools)
            skills = @($init.skills)
            mcp_servers = @($init.mcp_servers | ForEach-Object { $_.name })
            model = $init.model
            permission_mode = $init.permissionMode
        }
    } else { $null }
    $manifest.terminal_status = if ($null -eq $result) {
        'no_result'
    } elseif ($result.is_error -or $result.result -like 'Unknown command:*' -or $result.result -like 'Not logged in*') {
        'blocked'
    } else { $result.subtype }
    $manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding utf8
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $runRoot 'runner-error.log') -Encoding utf8
    throw
}

Write-Output "Run root: $runRoot"
Write-Output "Workspace: $workspaceRoot"
Write-Output "Initial exit: $claudeExit"
