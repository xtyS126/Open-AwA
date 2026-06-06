<#
.SYNOPSIS
    代码审计脚本（OCR Viewer）—— 对未提交的代码变更进行全面审计。
.DESCRIPTION
    在完成每个重构阶段后运行此脚本，自动执行：
    1. Git diff 审查（变更文件列表 + 详细差异）
    2. Emoji 违规检查
    3. console.log 残留检查
    4. 前端 ESLint + TypeScript 类型检查
    5. 前端 Vitest 单元测试
    6. 后端 pytest 测试
    7. 生成审计报告（通过/不通过 + 问题清单）
.PARAMETER SkipTests
    跳过测试环节（仅 lint + typecheck）
.PARAMETER BackendOnly
    仅审计后端代码
.PARAMETER FrontendOnly
    仅审计前端代码
.PARAMETER Verbose
    输出详细 diff 内容
.EXAMPLE
    .\scripts\code-audit.ps1
    .\scripts\code-audit.ps1 -SkipTests
    .\scripts\code-audit.ps1 -FrontendOnly -Verbose
#>

param(
    [switch]$SkipTests,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path "$ScriptDir\.."
$ReportFile = "$RepoRoot\reports\audit-result.txt"
$Failures = @()
$Warnings = @()
$Passes = @()

# ANSI 颜色支持
function Write-ColorLine($Text, $Color) {
    if ($Color -eq 'Green') { Write-Host "  [PASS] $Text" -ForegroundColor Green }
    elseif ($Color -eq 'Red') { Write-Host "  [FAIL] $Text" -ForegroundColor Red }
    elseif ($Color -eq 'Yellow') { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
    else { Write-Host "  [INFO] $Text" }
}

function Add-Pass($Check) {
    $global:Passes += $Check
    Write-ColorLine $Check 'Green'
}
function Add-Fail($Check) {
    $global:Failures += $Check
    Write-ColorLine $Check 'Red'
}
function Add-Warn($Check) {
    $global:Warnings += $Check
    Write-ColorLine $Check 'Yellow'
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Open-AwA 代码审计 (OCR Viewer)" -ForegroundColor Cyan
Write-Host "  运行时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1. Git 状态检查
# ============================================================
Write-Host "[1/7] Git 状态检查" -ForegroundColor Cyan
Push-Location $RepoRoot

$gitStatus = git status --porcelain
if (-not $gitStatus) {
    Add-Fail "没有未提交的变更，无需审计"
    Pop-Location
    exit 1
}

$changedFiles = ($gitStatus | Measure-Object).Count
Write-ColorLine "发现 $changedFiles 个变更文件" 'White'

# 分类变更文件
$addedFiles = ($gitStatus | Select-String -Pattern '^A|^\?\?' | Measure-Object).Count
$modifiedFiles = ($gitStatus | Select-String -Pattern '^ M|^M ' | Measure-Object).Count
$deletedFiles = ($gitStatus | Select-String -Pattern '^ D' | Measure-Object).Count
Write-ColorLine "  新增: $addedFiles, 修改: $modifiedFiles, 删除: $deletedFiles" 'White'

# 输出变更文件列表
Write-Host "  变更文件列表:"
git status --short | ForEach-Object { Write-Host "    $_" }

if ($Verbose) {
    Write-Host ""
    Write-Host "  详细差异:" -ForegroundColor Gray
    git diff --stat
}

# 检查变更是否涉及前端/后端
$hasFrontendChanges = ($gitStatus | Select-String -Pattern 'frontend/' | Measure-Object).Count -gt 0
$hasBackendChanges = ($gitStatus | Select-String -Pattern 'backend/' | Measure-Object).Count -gt 0

Add-Pass "Git 状态: $changedFiles 个变更文件"

# ============================================================
# 2. Emoji 违规检查
# ============================================================
Write-Host ""
Write-Host "[2/7] Emoji 违规检查" -ForegroundColor Cyan

# 获取所有变更的文本文件
$changedTextFiles = git diff --name-only --diff-filter=ACM | Where-Object {
    $_ -match '\.(ts|tsx|css|py|md|yml|yaml|json|html|js)$'
}

$emojiRegex = [regex]::new('[\p{So}\p{Sk}]')
$emojiFound = $false

foreach ($file in $changedTextFiles) {
    $fullPath = Join-Path $RepoRoot $file
    if (-not (Test-Path $fullPath)) { continue }

    $content = Get-Content $fullPath -Raw -ErrorAction SilentlyContinue
    if (-not $content) { continue }

    # 检测通用 emoji（排除 ASCII 标点等）
    $matches = [regex]::Matches($content, '[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}]')
    if ($matches.Count -gt 0) {
        $emojiFound = $true
        foreach ($m in $matches) {
            Add-Fail "Emoji: $file 中发现 emoji 字符 '$($m.Value)'"
        }
    }
}

if (-not $emojiFound) {
    Add-Pass "无 Emoji 违规"
}

# ============================================================
# 3. 调试代码残留检查（仅生产文件）
# ============================================================
Write-Host ""
Write-Host "[3/7] 调试代码残留检查" -ForegroundColor Cyan

$debugFound = $false
foreach ($file in $changedTextFiles) {
    $fullPath = Join-Path $RepoRoot $file
    if (-not (Test-Path $fullPath)) { continue }

    # 跳过测试文件
    if ($file -match '__tests__|\.test\.|\.spec\.') { continue }

    $content = Get-Content $fullPath -Raw -ErrorAction SilentlyContinue
    $lines = Get-Content $fullPath -ErrorAction SilentlyContinue

    # 检查 console.log/debug/info（排除 error/warn）
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match 'console\.(log|debug|info)\(') {
            $debugFound = $true
            Add-Warn "调试代码: $file : $($i+1) 行包含 console.$($Matches[1])()"
        }
    }

    # 检查 debugger 语句
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '\bdebugger\b') {
            $debugFound = $true
            Add-Fail "调试代码: $file : $($i+1) 行包含 debugger 语句"
        }
    }
}

if (-not $debugFound) {
    Add-Pass "无调试代码残留"
}

# ============================================================
# 4. 前端 ESLint + TypeScript 检查
# ============================================================
if (-not $BackendOnly -and $hasFrontendChanges) {
    Write-Host ""
    Write-Host "[4/7] 前端 ESLint + TypeScript 类型检查" -ForegroundColor Cyan

    Push-Location "$RepoRoot\frontend"

    # TypeScript 类型检查
    $tsOutput = npm run typecheck 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "TypeScript 类型检查通过"
    } else {
        Add-Fail "TypeScript 类型检查失败"
        if ($Verbose) {
            $tsOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
        }
        # 显示最后 20 行错误
        $tsErrors = ($tsOutput | Select-String -Pattern 'error TS')
        if ($tsErrors) {
            $tsErrors | Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        }
    }

    # ESLint
    $lintOutput = npm run lint 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "ESLint 检查通过"
    } else {
        $lintErrors = ($lintOutput | Select-String -Pattern 'error|warning' | Measure-Object).Count
        if ($lintErrors -gt 0) {
            Add-Fail "ESLint 检查: $lintErrors 个问题"
            if ($Verbose) {
                $lintOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
            }
            $lintOutput | Select-String -Pattern 'error|warning' | Select-Object -Last 30 | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
        } else {
            Add-Pass "ESLint 检查通过"
        }
    }

    Pop-Location
} else {
    Write-Host ""
    Write-Host "[4/7] 前端检查 — 跳过（无前端变更）" -ForegroundColor Gray
}

# ============================================================
# 5. 前端单元测试
# ============================================================
if (-not $SkipTests -and -not $BackendOnly -and $hasFrontendChanges) {
    Write-Host ""
    Write-Host "[5/7] 前端 Vitest 单元测试" -ForegroundColor Cyan

    Push-Location "$RepoRoot\frontend"

    $testOutput = npm run test 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "前端测试全部通过"
    } else {
        $failCount = ($testOutput | Select-String -Pattern 'failed' | Measure-Object).Count
        Add-Fail "前端测试有失败用例"
        $testOutput | Select-String -Pattern 'FAIL|failed|Error' | Select-Object -Last 30 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    }

    Pop-Location
} else {
    Write-Host ""
    Write-Host "[5/7] 前端测试 — 跳过" -ForegroundColor Gray
}

# ============================================================
# 6. 后端测试
# ============================================================
if (-not $SkipTests -and -not $FrontendOnly -and $hasBackendChanges) {
    Write-Host ""
    Write-Host "[6/7] 后端 pytest 测试" -ForegroundColor Cyan

    Push-Location "$RepoRoot\backend"

    $testOutput = python -m pytest --tb=short 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "后端测试全部通过"
    } else {
        Add-Fail "后端测试有失败用例"
        $testOutput | Select-String -Pattern 'FAILED|ERRORS|failed' | Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    }

    Pop-Location
} else {
    Write-Host ""
    Write-Host "[6/7] 后端测试 — 跳过" -ForegroundColor Gray
}

# ============================================================
# 7. 注释规范检查
# ============================================================
Write-Host ""
Write-Host "[7/7] 注释规范检查" -ForegroundColor Cyan

$chineseCommentFound = $false
foreach ($file in $changedTextFiles) {
    $fullPath = Join-Path $RepoRoot $file
    if (-not (Test-Path $fullPath)) { continue }
    if ($file -match '__tests__|\.test\.|\.spec\.') { continue }

    $newLines = git diff --unified=0 $fullPath 2>$null | Select-String -Pattern '^\+' | ForEach-Object { $_.Line }
    # 仅检查新增的注释行
    $newCommentLines = $newLines | Where-Object { $_ -match '^\+\s*(//|#|/\*\*|\*)' }
    # 大多数新增注释应为中文（CLAUDE.md 规范）
    # 这里仅做提醒，不强制失败
    if ($newCommentLines) {
        $chineseCommentFound = $true
    }
}

if ($chineseCommentFound) {
    Add-Pass "注释规范 — 新增注释已检查（提醒：注释需使用中文）"
} else {
    Add-Pass "注释规范 — 无新增注释行"
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

# 生成报告文件
$reportContent = @"
Open-AwA 代码审计报告
======================
运行时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
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
    Write-Host ""
    exit 1
} elseif ($totalWarnings -gt 0) {
    Write-Host "  结论: [有条件通过] 有 $totalWarnings 个警告，请人工确认" -ForegroundColor Yellow
    Write-Host "  详细报告: $ReportFile" -ForegroundColor Gray
    Write-Host ""
    exit 0
} else {
    Write-Host "  结论: [通过] 所有检查项通过，代码可以提交" -ForegroundColor Green
    Write-Host "  详细报告: $ReportFile" -ForegroundColor Gray
    Write-Host ""
    exit 0
}
