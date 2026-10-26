# 课表转日历 skill — 本地安装脚本（Windows PowerShell）
#
#   .\install.ps1                       # 自动选择 skills 目录
#   .\install.ps1 -Target D:\skills     # 指定目录
#
param(
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$Name = "syllabus-to-ics"
$Src  = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $Target) {
    foreach ($d in @("$env:USERPROFILE\.codebuddy\skills", "$env:USERPROFILE\.claude\skills")) {
        if (Test-Path $d) { $Target = $d; break }
    }
}
if (-not $Target) {
    $Target = "$env:USERPROFILE\.codebuddy\skills"
    Write-Host "未找到现成的 skills 目录，将新建：$Target"
}
New-Item -ItemType Directory -Force -Path $Target | Out-Null

$Dest = Join-Path $Target $Name
if (Test-Path $Dest) {
    Write-Host "已存在 $Dest，先备份为 $Dest.bak"
    if (Test-Path "$Dest.bak") { Remove-Item -Recurse -Force "$Dest.bak" }
    Move-Item $Dest "$Dest.bak"
}

# 复制（排除 .git 与缓存）
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Get-ChildItem -Path $Src -Force | Where-Object {
    $_.Name -notin @(".git", "__pycache__")
} | ForEach-Object {
    Copy-Item $_.FullName -Destination $Dest -Recurse -Force
}
Get-ChildItem -Path $Dest -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "✅ 已安装到 $Dest" -ForegroundColor Green

# 自检
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Host "⚠ 没找到 python，脚本无法运行。请先安装 Python 3.9+。" -ForegroundColor Yellow
    exit 1
}
Write-Host ("使用 " + (& $py.Source --version 2>&1))
Push-Location $Dest
try {
    & $py.Source -m unittest discover -s tests
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "下一步："
Write-Host "  1) 把课表 PDF 丢给 AI，说“按 syllabus-to-ics 流程生成日历”"
Write-Host "  2) 解析 PDF 需要：python -m pip install pymupdf"
Write-Host "  3) 手动跑：python $Dest\scripts\build.py -c 配置.json -o 课表.ics"
