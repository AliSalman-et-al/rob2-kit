$ErrorActionPreference = "Stop"

function Invoke-Checked([string]$program, [string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$program failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked "uv" @("run", "ruff", "format", "--check", "src", "tests", "docs/release")
Invoke-Checked "uv" @("run", "ruff", "check", "src", "tests", "docs/release")
Invoke-Checked "uv" @("run", "ty", "check", "src", "tests", "docs/release")
Invoke-Checked "uv" @("run", "python", "-m", "rob2_kit.contract_manifest", "--output", "docs/release/public-contract.json")
Invoke-Checked "uv" @("run", "python", "docs/release/verify.py")
Invoke-Checked "uv" @("run", "pytest", "-q")
Invoke-Checked "uv" @("build", "--wheel", "--out-dir", "dist")
$wheel = Join-Path (Resolve-Path dist) "rob2_kit-0.9.0-py3-none-any.whl"
Invoke-Checked "uv" @("run", "python", "docs/release/verify.py", "--wheel", $wheel)

Write-Output "v0.9 verification passed"
