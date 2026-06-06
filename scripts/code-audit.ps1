<#
.SYNOPSIS
    代码审计脚本 — 集成 ocr (OpenCodeReview) AI 审查 + 自动化检查。
.DESCRIPTION
    在完成每个重构阶段或 git commit 前运行此脚本，自动执行：
    1. Git 状态检查（变更文件列表）
    2. ocr AI 代码审查（@alibaba-group/open-code-review）
    3. 前端 ESLint + TypeScript 类型检查
    4. 前端 Vitest 单元测试
    5. 后端 pytest 测试
    6. 生成审计报告（通过/不通过 + 问题清单）
.PARAMETER SkipOcr
    跳过 ocr AI 审查（仅运行 lint + typecheck + tests）
.PARAMETER SkipTests
    跳过测试环节（仅 lint + typecheck）
.PARAMETER BackendOnly
    仅审计后端代码
.PARAMETER FrontendOnly
    仅审计前端代码
.PARAMETER Verbose
    输出详细 diff 和审查内容
.EXAMPLE
    .\scripts\code-audit.ps1
    .\scripts\code-audit.ps1 -SkipOcr -SkipTests
    .\scripts\code-audit.ps1 -FrontendOnly -Verbose
#>

param(
    [switch]$SkipOcr,
    [switch]$SkipTests,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
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

function Add-Pass($Check) { $global:Passes += $Check; Write-ColorLine $Check 'Green' }
function Add-Fail($Check) { $global:Failures += $Check; Write-ColorLine $Check 'Red' }
function Add-Warn($Check) { $global:Warnings += $Check; Write-ColorLine $Check 'Yellow' }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Open-AwA 代码审计" -ForegroundColor Cyan
Write-Host "  运行时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $RepoRoot

# ============================================================
# 1. Git 状态检查
# ============================================================
Write-Host "[1/6] Git 状态检查" -ForegroundColor Cyan

$gitStatus = git status --porcelain
if (-not $gitStatus) {
    Add-Fail "没有未提交的变更，无需审计"
    Pop-Location
    exit 1
}

$changedFiles = ($gitStatus | Measure-Object).Count
Write-ColorLine "发现 $changedFiles 个变更文件" 'White'

$addedFiles = ($gitStatus | Select-String -Pattern '^A|^\?\?' | Measure-Object).Count
$modifiedFiles = ($gitStatus | Select-String -Pattern '^ M|^M ' | Measure-Object).Count
$deletedFiles = ($gitStatus | Select-String -Pattern '^ D' | Measure-Object).Count
Write-ColorLine "  新增: $addedFiles, 修改: $modifiedFiles, 删除: $deletedFiles" 'White'

Write-Host "  变更文件列表:"
git status --short | ForEach-Object { Write-Host "    $_" }

$hasFrontendChanges = ($gitStatus | Select-String -Pattern 'frontend/' | Measure-Object).Count -gt 0
$hasBackendChanges = ($gitStatus | Select-String -Pattern 'backend/' | Measure-Object).Count -gt 0

Add-Pass "Git 状态: $changedFiles 个变更文件"

# ============================================================
# 2. ocr AI 代码审查（核心步骤）
# ============================================================
Write-Host ""
Write-Host "[2/6] ocr AI 代码审查 (OpenCodeReview)" -ForegroundColor Cyan

if ($SkipOcr) {
    Write-Host "  跳过 ocr 审查（--skip-ocr）" -ForegroundColor Gray
} else {
    $ocrAvailable = Get-Command ocr -ErrorAction SilentlyContinue
    if (-not $ocrAvailable) {
        Add-Warn "ocr 命令不可用，请执行 npm install -g @alibaba-group/open-code-review"
    } else {
        try {
            # 获取 git diff 并通过 ocr 审查
            $diffContent = git diff HEAD
            if (-not $diffContent) {
                $diffContent = git diff --cached
            }

            if ($diffContent) {
                # 通过临时文件传递 diff 内容给 ocr
                $tempDiffFile = [System.IO.Path]::GetTempFileName() + ".diff"
                $diffContent | Out-File -FilePath $tempDiffFile -Encoding UTF8

                Write-Host "  正在运行 ocr AI 审查..." -ForegroundColor Gray
                $ocrOutput = ocr review --diff-file $tempDiffFile 2>&1

                # 保存 ocr 原始输出
                $ocrOutput | Out-File -FilePath $OcrReportFile -Encoding UTF8

                # 分析 ocr 输出：查找建议/错误级别问题
                $ocrIssues = ($ocrOutput | Select-String -Pattern 'error|warning|建议|问题|issue' -CaseSensitive:$false | Measure-Object).Count

                if ($Verbose) {
                    Write-Host "  --- ocr 审查输出 ---" -ForegroundColor Gray
                    $ocrOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
                    Write-Host "  --- 审查结束 ---" -ForegroundColor Gray
                }

                if ($ocrOutput -match 'error|Error|ERROR') {
                    $errorLines = ($ocrOutput | Select-String -Pattern 'error|Error|ERROR')
                    foreach ($line in $errorLines) {
                        Add-Fail "ocr: $line"
                    }
                } elseif ($ocrIssues -gt 0) {
                    Add-Warn "ocr 审查发现 $ocrIssues 个建议项，请查看 $OcrReportFile"
                    if ($Verbose) {
                        $ocrOutput | Select-Object -Last 40 | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
                    }
                } else {
                    Add-Pass "ocr AI 审查通过 — 无问题发现"
                }

                Remove-Item $tempDiffFile -ErrorAction SilentlyContinue
            } else {
                Add-Pass "ocr AI 审查 — 无变更内容（仅二进制/删除文件）"
            }
        } catch {
            Add-Warn "ocr 审查执行异常: $_"
        }
    }
}

# ============================================================
# 3. 前端 ESLint + TypeScript 检查
# ============================================================
if (-not $BackendOnly -and $hasFrontendChanges) {
    Write-Host ""
    Write-Host "[3/6] 前端 ESLint + TypeScript 类型检查" -ForegroundColor Cyan

    Push-Location "$RepoRoot\frontend"

    # TypeScript 类型检查 — 仅检查变更文件中的新错误
    $tsOutput = npm run typecheck 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "TypeScript 类型检查通过"
    } else {
        # 过滤出变更文件中的错误
        $changedTsFiles = git diff --name-only HEAD | Where-Object { $_ -match '\.(ts|tsx)$' -and $_ -notmatch '__tests__|\.test\.|\.spec\.' }
        $newErrors = @()
        foreach ($file in $changedTsFiles) {
            $shortPath = $file -replace '^frontend/', ''
            $fileErrors = ($tsOutput | Select-String -Pattern [regex]::Escape($shortPath))
            if ($fileErrors) { $newErrors += $fileErrors }
        }
        if ($newErrors.Count -gt 0) {
            Add-Fail "TypeScript 类型检查: 变更文件中有 $($newErrors.Count) 个新错误"
            $newErrors | Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        } else {
            Add-Pass "TypeScript 类型检查 — 变更文件无新错误（已有错误未计入）"
        }
    }

    # ESLint
    $lintOutput = npm run lint 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "ESLint 检查通过"
    } else {
        $newLintErrors = @()
        foreach ($file in $changedTsFiles) {
            $shortPath = $file -replace '^frontend/', ''
            $fileLintErrors = ($lintOutput | Select-String -Pattern [regex]::Escape($shortPath))
            if ($fileLintErrors) { $newLintErrors += $fileLintErrors }
        }
        if ($newLintErrors.Count -gt 0) {
            Add-Fail "ESLint: 变更文件中有 $($newLintErrors.Count) 个问题"
            $newLintErrors | Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
        } else {
            Add-Pass "ESLint — 变更文件无新问题（已有问题未计入）"
        }
    }

    Pop-Location
} else {
    Write-Host ""
    Write-Host "[3/6] 前端检查 — 跳过（无前端变更）" -ForegroundColor Gray
}

# ============================================================
# 4. Emoji + 调试代码快速检查
# ============================================================
Write-Host ""
Write-Host "[4/6] 代码规范快速检查" -ForegroundColor Cyan

$changedTextFiles = git diff --name-only --diff-filter=ACM HEAD | Where-Object {
    $_ -match '\.(ts|tsx|css|py|md|yml|yaml|json|html|js)$'
}

$emojiFound = $false
$debugFound = $false

foreach ($file in $changedTextFiles) {
    $fullPath = Join-Path $RepoRoot $file
    if (-not (Test-Path $fullPath)) { continue }
    if ($file -match '__tests__|\.test\.|\.spec\.') { continue }

    $lines = Get-Content $fullPath -ErrorAction SilentlyContinue

    # Emoji 检查
    $emojiMatches = [regex]::Matches((Get-Content $fullPath -Raw -ErrorAction SilentlyContinue),
        '[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}]')
    foreach ($m in $emojiMatches) {
        $emojiFound = $true
        Add-Fail "Emoji: $file 中发现 emoji '$($m.Value)'"
    }

    # debugger/console 检查
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '\bdebugger\b') {
            $debugFound = $true
            Add-Fail "调试代码: $file : $($i+1) 行包含 debugger"
        }
        if ($lines[$i] -match 'console\.(log|debug|info)\(') {
            $debugFound = $true
            Add-Warn "调试代码: $file : $($i+1) 行包含 console.$($Matches[1])()"
        }
    }
}

if (-not $emojiFound) { Add-Pass "无 Emoji 违规" }
if (-not $debugFound) { Add-Pass "无调试代码残留" }

# ============================================================
# 5. 前端单元测试
# ============================================================
if (-not $SkipTests -and -not $BackendOnly -and $hasFrontendChanges) {
    Write-Host ""
    Write-Host "[5/6] 前端 Vitest 单元测试" -ForegroundColor Cyan

    Push-Location "$RepoRoot\frontend"

    $testOutput = npm run test 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "前端测试全部通过"
    } else {
        $failCount = ($testOutput | Select-String -Pattern 'failed' | Measure-Object).Count
        Add-Fail "前端测试有失败用例"
        $testOutput | Select-String -Pattern 'FAIL|failed|Error' | Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    }

    Pop-Location
} else {
    Write-Host ""
    Write-Host "[5/6] 前端测试 — 跳过" -ForegroundColor Gray
}

# ============================================================
# 6. 后端测试
# ============================================================
if (-not $SkipTests -and -not $FrontendOnly -and $hasBackendChanges) {
    Write-Host ""
    Write-Host "[6/6] 后端 pytest 测试" -ForegroundColor Cyan

    Push-Location "$RepoRoot\backend"

    $testOutput = python -m pytest --tb=short 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "后端测试全部通过"
    } else {
        Add-Fail "后端测试有失败用例"
        $testOutput | Select-String -Pattern 'FAILED|ERRORS|failed' | Select-Object -Last 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    }

    Pop-Location
} else {
    Write-Host ""
    Write-Host "[6/6] 后端测试 — 跳过" -ForegroundColor Gray
}

# ============================================================
# 汇总报告
# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  审计结果汇总" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$totalFailures = $Failures.Count
$totalWarnings = $Warnings.Count
$totalPasses = $Passes.Count

Write-Host "  通过: $totalPasses 项" -ForegroundColor Green
Write-Host "  警告: $totalWarnings 项" -ForegroundColor Yellow
Write-Host "  失败: $totalFailures 项" -ForegroundColor Red
Write-Host ""

$reportContent = @"
Open-AwA 代码审计报告
======================
运行时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
审计工具: ocr (OpenCodeReview) + ESLint + TypeScript + pytest
变更文件: $changedFiles 个 (新增: $addedFiles, 修改: $modifiedFiles, 删除: $deletedFiles)

===== 通过 ($totalPasses 项) =====
$($Passes -join "`n")

===== 警告 ($totalWarnings 项) =====
$($Warnings -join "`n")

===== 失败 ($totalFailures 项) =====
$($Failures -join "`n")

最终结果: $(if ($totalFailures -eq 0) { '通过 — 可以提交' } else { '不通过 — 需要修复' })
"@
Set-Content -Path $ReportFile -Value $reportContent -Encoding UTF8

Pop-Location

if ($totalFailures -gt 0) {
    Write-Host "  结论: [不通过] 发现 $totalFailures 个需要修复的问题" -ForegroundColor Red
    Write-Host "  详细报告: $ReportFile" -ForegroundColor Gray
    if (Test-Path $OcrReportFile) { Write-Host "  ocr 审查: $OcrReportFile" -ForegroundColor Gray }
    Write-Host ""
    exit 1
} elseif ($totalWarnings -gt 0) {
    Write-Host "  结论: [有条件通过] 有 $totalWarnings 个警告，请检查后确认" -ForegroundColor Yellow
    Write-Host "  详细报告: $ReportFile" -ForegroundColor Gray
    if (Test-Path $OcrReportFile) { Write-Host "  ocr 审查: $OcrReportFile" -ForegroundColor Gray }
    Write-Host ""
    exit 0
} else {
    Write-Host "  结论: [通过] 所有检查通过，可以安全提交" -ForegroundColor Green
    Write-Host "  详细报告: $ReportFile" -ForegroundColor Gray
    Write-Host ""
    exit 0
}
