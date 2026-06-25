#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Smart `git commit` wrapper that auto-stages any files the pre-commit
    hooks fixed, then retries the commit once.

.DESCRIPTION
    The standard pre-commit flow is:
      1. git commit -m "..."
      2. ruff / formatters auto-fix files
      3. commit aborts because files changed under the hook
      4. you manually `git add -u`
      5. you re-run `git commit -m "..."`

    This script collapses steps 2-5 into one. You commit. If the hooks
    auto-fixed something, the script stages the fixes and retries the
    commit with the same message. If the hooks failed for a non-fixable
    reason (e.g. bandit, mypy), the commit aborts and you fix manually.

.PARAMETER Message
    The commit message. Required.

.EXAMPLE
    .\scripts\commit.ps1 -Message "feat: add foo"
    Commits with the message; auto-fixes + restages once if needed.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Message
)

# Activate venv if present.
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & ".\.venv\Scripts\Activate.ps1"
}

# Attempt 1 — normal commit. Pre-commit hook will run.
git commit -m "$Message"
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Committed cleanly on first try." -ForegroundColor Green
    exit 0
}

# If we got here, the commit failed. Most commonly because pre-commit
# auto-fixed files (which makes the working tree dirty and aborts).
# Check whether there are tracked files with unstaged modifications.
$modified = git diff --name-only
if (-not $modified) {
    Write-Host "✗ Commit failed and no auto-fixes were applied." -ForegroundColor Red
    Write-Host "  Likely a non-fixable hook error (bandit, mypy, etc.)." -ForegroundColor Yellow
    Write-Host "  Fix manually and re-run." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Pre-commit fixed these files:" -ForegroundColor Cyan
$modified -split "`n" | ForEach-Object { Write-Host "  • $_" -ForegroundColor White }
Write-Host ""

# Stage the auto-fixes.
git add -u
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ git add -u failed." -ForegroundColor Red
    exit 1
}

# Attempt 2 — retry with the same message. The hook runs again; if the
# fixes were idempotent (and they should be for ruff/black/format), this
# pass is clean.
Write-Host "Retrying commit..." -ForegroundColor Cyan
git commit -m "$Message"
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Committed after auto-fix." -ForegroundColor Green
    exit 0
}

Write-Host "✗ Commit still failing after auto-fix." -ForegroundColor Red
Write-Host "  A non-fixable hook (bandit, mypy, etc.) reported an issue." -ForegroundColor Yellow
Write-Host "  Run `pre-commit run --all-files` to see the full report." -ForegroundColor Yellow
exit 1
