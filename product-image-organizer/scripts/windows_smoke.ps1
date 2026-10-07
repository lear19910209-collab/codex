param([string]$Executable)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Executable)) { throw "找不到 Windows exe：$Executable" }
$process = Start-Process -FilePath $Executable -PassThru
Start-Sleep -Seconds 8
$process.Refresh()
if ($process.HasExited) { throw "Windows 桌面软件提前退出，退出码：$($process.ExitCode)" }
# A hidden Qt error dialog alone must not count as the application's main window.
if ($process.MainWindowTitle -ne "商品图批量整理器") { throw "没有找到商品图批量整理器主窗口，实际标题：$($process.MainWindowTitle)" }
Write-Host "Windows 打包软件启动成功：$($process.MainWindowTitle)"
$process.CloseMainWindow() | Out-Null
if (-not $process.WaitForExit(15000)) { $process.Kill(); throw "软件未能正常关闭" }
if ($process.ExitCode -ne 0) { throw "软件关闭时异常：$($process.ExitCode)" }
$checkFolder = Join-Path $env:RUNNER_TEMP ([Guid]::NewGuid().ToString())
$check = Start-Process -FilePath $Executable -ArgumentList @('--verify-package', "`"$checkFolder`"") -PassThru -Wait
if ($check.ExitCode -ne 0) { throw "打包软件图片处理校验失败：$($check.ExitCode)" }
$report = Get-Content (Join-Path $checkFolder 'package-check.json') -Raw | ConvertFrom-Json
if (-not $report.passed) { throw "打包软件图片处理校验失败：$($report.reason)" }
Write-Host ($report.checks -join '；')
