<#
.SYNOPSIS
    Open-AwA code audit script - integrates ocr (OpenCodeReview) AI review.
.DESCRIPTION
    Run before git commit. Steps:
    1. Git status check
    2. ocr AI code review
    3. Frontend ESLint + TypeScript
    4. Code hygiene (emoji, debugger, console.log)
    5. Frontend tests
    6. Backend tests
.EXAMPLE
    .\scripts\code-audit.ps1
    .\scripts\code-audit.ps1 -SkipOcr -FrontendOnly
    .\scripts\code-audit.ps1 -Verbose
#>

param(
    [switch]$SkipOcr,
    [switch]$SkipTests,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path "$ScriptDir\.."
$ReportFile = "$RepoRoot\reports\audit-result.txt"
$OcrReportFile = "$RepoRoot\reports\ocr-review.txt"
$Failures = @()
$Warnings = @()
$Passes = @()

function Write-ColorLine($Text, $Color) {
    if ($Color -eq 'Green') { Write-Host "  [PASS] $Text" -ForegroundColor Green }
    elseif ($Color -eq 'Red') { Write-Host "  [FAIL] $Text" -ForegroundColor Red }
    elseif ($Color -eq 'Yellow') { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
    else { Write-Host "  [INFO] $Text" }
}

function Add-Pass($Check) { $script:Passes += $Check; Write-ColorLine $Check 'Green' }
function Add-Fail($Check) { $script:Failures += $Check; Write-ColorLine $Check 'Red' }
function Add-Warn($Check) { $script:Warnings += $Check; Write-ColorLine $Check 'Yellow' }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Open-AwA Code Audit" -ForegroundColor Cyan
Write-Host "  Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $RepoRoot

# ============================================================
# Step 1: Git status
# ============================================================
Write-Host "[1/6] Git status check" -ForegroundColor Cyan

$gitStatus = git status --porcelain 2>$null
if (-not $gitStatus) {
    Add-Fail "No uncommitted changes, nothing to audit"
    Pop-Location
    exit 1
}

$changedFiles = ($gitStatus | Measure-Object).Count
Write-ColorLine "Found $changedFiles changed files" 'White'

$addedFiles = ($gitStatus | Select-String -Pattern '^A|^\?\?' | Measure-Object).Count
$modifiedFiles = ($gitStatus | Select-String -Pattern '^ M|^M ' | Measure-Object).Count
$deletedFiles = ($gitStatus | Select-String -Pattern '^ D' | Measure-Object).Count
Write-ColorLine "  Added: $addedFiles, Modified: $modifiedFiles, Deleted: $deletedFiles" 'White'

Write-Host "  Changed files:"
git status --short | ForEach-Object { Write-Host "    $_" }

$hasFrontendChanges = ($gitStatus | Select-String -Pattern 'frontend/' | Measure-Object).Count -gt 0
$hasBackendChanges = ($gitStatus | Select-String -Pattern 'backend/' | Measure-Object).Count -gt 0

Add-Pass "Git status: $changedFiles changed files"

# ============================================================
# Step 2: ocr AI code review
# ============================================================
Write-Host ""
Write-Host "[2/6] ocr AI Code Review (OpenCodeReview)" -ForegroundColor Cyan

if ($SkipOcr) {
    Write-Host "  Skipped (--skip-ocr)" -ForegroundColor Gray
}
else {
    $ocrCmd = $null
    $localExe = Join-Path $ScriptDir "opencodereview.exe"

    if (Test-Path $localExe) {
        $ocrCmd = $localExe
    }
    else {
        $globalOcr = Get-Command ocr -ErrorAction SilentlyContinue
        if ($globalOcr) { $ocrCmd = "ocr" }
    }

    if (-not $ocrCmd) {
        Add-Warn "ocr not found. Install: npm install -g @alibaba-group/open-code-review"
    }
    else {
        $diffContent = git diff HEAD 2>$null
        if (-not $diffContent) { $diffContent = git diff --cached 2>$null }

        if ($diffContent) {
            Write-Host "  Running ocr AI review..." -ForegroundColor Gray
            $ocrExitCode = 0
            $ocrOutput = ""
            try {
                if ($ocrCmd -eq "ocr") {
                    $ocrOutput = ocr review --audience agent 2>&1
                }
                else {
                    $ocrOutput = & $ocrCmd review --audience agent 2>&1
                }
            }
            catch {
                $ocrOutput = $_.Exception.Message
                $ocrExitCode = 1
            }

            if ($ocrOutput) {
                $ocrOutput | Out-File -FilePath $OcrReportFile -Encoding UTF8
            }

            if ($Verbose) {
                Write-Host "  --- ocr output ---" -ForegroundColor Gray
                if ($ocrOutput) { $ocrOutput | ForEach-Object { Write-Host "    $_" } }
                Write-Host "  --- end ---" -ForegroundColor Gray
            }

            if ($ocrOutput -and ($ocrOutput -match 'error|Error|ERROR|FAIL')) {
                $errorLines = ($ocrOutput | Select-String -Pattern 'error|Error|ERROR|FAIL')
                foreach ($line in $errorLines) {
                    Add-Fail "ocr: $line"
                }
            }
            elseif ($ocrOutput -and ($ocrOutput -match 'warning|建议|WARN|issue|问题')) {
                $warnCount = ($ocrOutput | Select-String -Pattern 'warning|建议|WARN|issue|问题').Count
                Add-Warn "ocr review: $warnCount suggestions. See $OcrReportFile"
            }
            else {
                Add-Pass "ocr AI review passed"
            }

        }
        else {
            Add-Pass "ocr AI review: no text changes to review"
        }
    }
}

# ============================================================
# Step 3: Frontend ESLint + TypeScript (new errors only)
# ============================================================
if (-not $BackendOnly -and $hasFrontendChanges) {
    Write-Host ""
    Write-Host "[3/6] Frontend ESLint + TypeScript" -ForegroundColor Cyan

    $prevLocation = Get-Location
    Set-Location "$RepoRoot\frontend"

    $changedTsFiles = git diff --name-only HEAD 2>$null | Where-Object { $_ -match '\.(ts|tsx)$' -and $_ -notmatch '__tests__|\.test\.|\.spec\.' }

    if ($changedTsFiles) {
        $tsOutput = npm run typecheck 2>&1
        if ($LASTEXITCODE -eq 0) {
            Add-Pass "TypeScript: passed"
        }
        else {
            $newTsErrors = @()
            foreach ($f in $changedTsFiles) {
                $short = $f -replace '^frontend/', ''
                $errs = ($tsOutput | Select-String -Pattern ([regex]::Escape($short)))
                if ($errs) { $newTsErrors += $errs }
            }
            if ($newTsErrors.Count -gt 0) {
                Add-Fail "TypeScript: $($newTsErrors.Count) new errors in changed files"
                $newTsErrors | Select-Object -Last 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
            }
            else {
                Add-Pass "TypeScript: no new errors in changed files (pre-existing errors ignored)"
            }
        }

        $lintOutput = npm run lint 2>&1
        if ($LASTEXITCODE -eq 0) {
            Add-Pass "ESLint: passed"
        }
        else {
            $newLintErrors = @()
            foreach ($f in $changedTsFiles) {
                $short = $f -replace '^frontend/', ''
                $errs = ($lintOutput | Select-String -Pattern ([regex]::Escape($short)))
                if ($errs) { $newLintErrors += $errs }
            }
            if ($newLintErrors.Count -gt 0) {
                Add-Fail "ESLint: $($newLintErrors.Count) new issues in changed files"
                $newLintErrors | Select-Object -Last 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
            }
            else {
                Add-Pass "ESLint: no new issues in changed files (pre-existing ignored)"
            }
        }
    }
    else {
        Add-Pass "Frontend: no TS/TSX files changed"
    }

    Set-Location $prevLocation
}
else {
    Write-Host ""
    Write-Host "[3/6] Frontend check: skipped (no frontend changes)" -ForegroundColor Gray
}

# ============================================================
# Step 4: Code hygiene (emoji + debugger + console.log)
# ============================================================
Write-Host ""
Write-Host "[4/6] Code hygiene check" -ForegroundColor Cyan

$changedTextFiles = git diff --name-only --diff-filter=ACM HEAD 2>$null | Where-Object {
    $_ -match '\.(ts|tsx|css|py|md|yml|yaml|json|html|js)$'
}

$emojiFound = $false
$debugFound = $false

foreach ($file in $changedTextFiles) {
    $fullPath = Join-Path $RepoRoot $file
    if (-not (Test-Path $fullPath)) { continue }
    if ($file -match '__tests__|\.test\.|\.spec\.') { continue }

    $rawContent = Get-Content $fullPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $rawContent) { continue }

    # 使用 UTF-16 代理项表达补充平面字符，兼容 Windows PowerShell 5.1 的 .NET 正则实现
    $emojiPattern = '[\u2600-\u27BF\uFE00-\uFE0F]|(?:\uD83C[\uDDE0-\uDDFF\uDF00-\uDFFF])|(?:\uD83D[\uDC00-\uDEFF])|(?:\uD83E[\uDD00-\uDEFF])'
    $emojiMatches = [regex]::Matches($rawContent, $emojiPattern)
    foreach ($m in $emojiMatches) {
        $emojiFound = $true
        Add-Fail "Emoji: $file contains emoji '$($m.Value)'"
    }

    $lines = Get-Content $fullPath -Encoding UTF8 -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '\bdebugger\b') {
            $debugFound = $true
            Add-Fail "Debugger: $file line $($i+1)"
        }
        if ($lines[$i] -match 'console\.(log|debug|info)\(') {
            $debugFound = $true
            Add-Warn "console.$($Matches[1]): $file line $($i+1)"
        }
    }
}

if (-not $emojiFound) { Add-Pass "No emoji violations" }
if (-not $debugFound) { Add-Pass "No debug code residue" }

# ============================================================
# Step 5: Frontend tests
# ============================================================
if (-not $SkipTests -and -not $BackendOnly -and $hasFrontendChanges) {
    Write-Host ""
    Write-Host "[5/6] Frontend Vitest tests" -ForegroundColor Cyan

    $prevLocation = Get-Location
    Set-Location "$RepoRoot\frontend"

    $testOutput = npm run test 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "Frontend tests: all passed"
    }
    else {
        Add-Fail "Frontend tests: some failed"
        $testOutput | Select-String -Pattern 'FAIL|failed|Error' | Select-Object -Last 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    }

    Set-Location $prevLocation
}
else {
    Write-Host ""
    Write-Host "[5/6] Frontend tests: skipped" -ForegroundColor Gray
}

# ============================================================
# Step 6: Backend tests
# ============================================================
if (-not $SkipTests -and -not $FrontendOnly -and $hasBackendChanges) {
    Write-Host ""
    Write-Host "[6/6] Backend pytest" -ForegroundColor Cyan

    $prevLocation = Get-Location
    Set-Location "$RepoRoot\backend"

    $testOutput = python -m pytest --tb=short 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "Backend tests: all passed"
    }
    else {
        Add-Fail "Backend tests: some failed"
        $testOutput | Select-String -Pattern 'FAILED|ERRORS|failed' | Select-Object -Last 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    }

    Set-Location $prevLocation
}
else {
    Write-Host ""
    Write-Host "[6/6] Backend tests: skipped" -ForegroundColor Gray
}

# ============================================================
# Summary report
# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Audit Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$totalFailures = $Failures.Count
$totalWarnings = $Warnings.Count
$totalPasses = $Passes.Count

Write-Host "  Passed:  $totalPasses" -ForegroundColor Green
Write-Host "  Warnings: $totalWarnings" -ForegroundColor Yellow
Write-Host "  Failed:  $totalFailures" -ForegroundColor Red
Write-Host ""

$reportLines = @()
$reportLines += "Open-AwA Code Audit Report"
$reportLines += "========================="
$reportLines += "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$reportLines += "Changed files: $changedFiles (Added: $addedFiles, Modified: $modifiedFiles, Deleted: $deletedFiles)"
$reportLines += ""
$reportLines += "===== Passed ($totalPasses) ====="
$reportLines += $Passes
$reportLines += ""
$reportLines += "===== Warnings ($totalWarnings) ====="
$reportLines += $Warnings
$reportLines += ""
$reportLines += "===== Failed ($totalFailures) ====="
$reportLines += $Failures
$reportLines += ""
if ($totalFailures -eq 0) {
    $reportLines += "Result: PASSED - ready to commit"
} else {
    $reportLines += "Result: FAILED - fix issues before commit"
}

$reportTempFile = "$ReportFile.tmp"
try {
    # 先写同目录临时文件再原子替换，避免历史报告的只读 ACL 阻断本次审计
    $reportLines -join "`n" | Out-File -FilePath $reportTempFile -Encoding UTF8 -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $ReportFile) {
        try {
            Remove-Item -LiteralPath $ReportFile -Force -ErrorAction Stop
        }
        catch {
            # 旧报告可能由管理员账户创建，当前账户无法删除时保留旧文件并改写新报告
            $reportTimestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $ReportFile = Join-Path $RepoRoot "reports\audit-result-$reportTimestamp.txt"
        }
    }
    Move-Item -LiteralPath $reportTempFile -Destination $ReportFile -Force -ErrorAction Stop
}
catch {
    Write-Host "  [FAIL] Cannot write audit report: $($_.Exception.Message)" -ForegroundColor Red
    if (Test-Path -LiteralPath $reportTempFile) {
        Remove-Item -LiteralPath $reportTempFile -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
    exit 1
}

Pop-Location

if ($totalFailures -gt 0) {
    Write-Host "  Verdict: [FAILED] $totalFailures issues to fix" -ForegroundColor Red
    Write-Host "  Report: $ReportFile" -ForegroundColor Gray
    if (Test-Path $OcrReportFile) { Write-Host "  ocr: $OcrReportFile" -ForegroundColor Gray }
    Write-Host ""
    exit 1
}
elseif ($totalWarnings -gt 0) {
    Write-Host "  Verdict: [PASSED with warnings] $totalWarnings warnings, please review" -ForegroundColor Yellow
    Write-Host "  Report: $ReportFile" -ForegroundColor Gray
    if (Test-Path $OcrReportFile) { Write-Host "  ocr: $OcrReportFile" -ForegroundColor Gray }
    Write-Host ""
    exit 0
}
else {
    Write-Host "  Verdict: [PASSED] All checks passed, safe to commit" -ForegroundColor Green
    Write-Host "  Report: $ReportFile" -ForegroundColor Gray
    Write-Host ""
    exit 0
}
