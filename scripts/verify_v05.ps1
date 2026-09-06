$ErrorActionPreference = "Stop"

function Invoke-Checked([string]$program, [string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$program failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked "uv" @("run", "ruff", "format", "--check", ".")
Invoke-Checked "uv" @("run", "ruff", "check", ".")
Invoke-Checked "uv" @("run", "ty", "check")
Invoke-Checked "uv" @("run", "python", "-m", "rob2_kit.contract_manifest", "--output", "docs/release/public-contract.json")
Invoke-Checked "uv" @("run", "python", "docs/release/verify.py")
Invoke-Checked "uv" @("run", "pytest", "-q")
Invoke-Checked "uv" @("build", "--wheel", "--out-dir", "dist")
$wheel = Join-Path (Resolve-Path dist) "rob2_kit-0.5.0-py3-none-any.whl"
Invoke-Checked "uv" @("run", "python", "docs/release/verify.py", "--wheel", $wheel)

Write-Output "v0.5 verification passed"
