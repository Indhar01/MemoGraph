#!/usr/bin/env pwsh
<#
.SYNOPSIS
    One-shot installer for all local git hooks.

.DESCRIPTION
    Wires up:
      1. pre-commit hook  -> auto-fixes lint/format issues on every `git commit`
                              (configured in .pre-commit-config.yaml)
      2. pre-push hook    -> runs ruff / bandit / pip-audit / pytest before
                              every `git push` (configured in
                              scripts/pre-push.ps1)

    Run once after cloning the repo. Idempotent — safe to re-run.

.PARAMETER Remove
    Remove all hooks instead of installing them.

.EXAMPLE
    .\scripts\setup_hooks.ps1
    Install both hooks.

.EXAMPLE
    .\scripts\setup_hooks.ps1 -Remove
    Uninstall both hooks.
#>

[CmdletBinding()]
param(
    [switch]$Remove
)

function Write-Step { param([string]$Message) Write-Host "▶ $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "✓ $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "⚠ $Message" -ForegroundColor Yellow }
function Write-Err  { param([string]$Message) Write-Host "✗ $Message" -ForegroundColor Red }

if (-not (Test-Path ".git")) {
    Write-Err "Not in a Git repository. Run from the project root."
    exit 1
}

# Activate venv if present, so `pre-commit` resolves.
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & ".\.venv\Scripts\Activate.ps1"
}

if ($Remove) {
    Write-Step "Uninstalling pre-commit hook..."
    pre-commit uninstall 2>&1 | Out-Null
    Write-Ok "pre-commit hook removed (or was not installed)"

    Write-Step "Uninstalling pre-push hook..."
    & ".\scripts\setup_pre_push_hook.ps1" -Remove
    exit 0
}

# 1. pre-commit hook (auto-fixes on every `git commit`).
Write-Step "Installing pre-commit hook (auto-fix on commit)..."

# Verify pre-commit is available in the active environment.
pre-commit --version > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "pre-commit is not installed in this Python environment."
    Write-Host "  Install with: pip install -e `".[dev]`"" -ForegroundColor Gray
    exit 1
}

pre-commit install --overwrite
if ($LASTEXITCODE -ne 0) {
    Write-Err "pre-commit install failed."
    exit 1
}
Write-Ok "pre-commit hook installed"

# Optional but useful: also install for `git commit --amend` and merges.
pre-commit install --hook-type commit-msg --overwrite 2>&1 | Out-Null

# 2. pre-push hook (full CI check before `git push`).
Write-Step "Installing pre-push hook (runs ruff + bandit + pip-audit + tests)..."
& ".\scripts\setup_pre_push_hook.ps1" -Force

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✅ All git hooks installed" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""

Write-Host "What happens now:" -ForegroundColor Cyan
Write-Host "  • git commit  →  ruff, formatters, etc. AUTO-FIX your files." -ForegroundColor White
Write-Host "                  If any files were fixed, the commit ABORTS so" -ForegroundColor White
Write-Host "                  you can review with `git diff` and re-stage." -ForegroundColor White
Write-Host "                  Run `git add -u && git commit` to retry." -ForegroundColor White
Write-Host "  • git push    →  full ruff / bandit / pip-audit / tests run." -ForegroundColor White
Write-Host "                  Push aborts on failure." -ForegroundColor White
Write-Host ""

Write-Host "Bypass (rarely needed):" -ForegroundColor Cyan
Write-Host "  • Skip pre-commit once:  git commit --no-verify" -ForegroundColor White
Write-Host "  • Skip pre-push once:    git push --no-verify" -ForegroundColor White
Write-Host "  • Uninstall everything:  .\scripts\setup_hooks.ps1 -Remove" -ForegroundColor White
Write-Host ""
