$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv --without-pip .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败' }
}
python -m pip install --target .vendor --no-input -r requirements-mcp.txt
if ($LASTEXITCODE -ne 0) { throw '安装 MCP 依赖失败' }

Write-Host 'MCP 依赖已安装。使用 Codex CLI 注册：'
$mcpPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$mcpServer = Join-Path $projectRoot 'mcp_server.py'
Write-Host ('codex mcp add mspm0_serial -- "{0}" "{1}"' -f $mcpPython, $mcpServer)
