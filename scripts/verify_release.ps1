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
Invoke-Checked "uv" @("run", "python", "-m", "pytest", "-q")
Invoke-Checked "uv" @("run", "python", "scripts/build_release_wheel.py")

Write-Output "Release verification passed"
