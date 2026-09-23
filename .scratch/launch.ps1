$ErrorActionPreference = "SilentlyContinue"
$exe = "D:\TLGL\tlbb-explorer\app\src-tauri\target\debug\tlbb-shell.exe"
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9223"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $exe
$psi.UseShellExecute = $false          # 直接创建子进程，避开 shell 对环境变量的改写
$psi.EnvironmentVariables["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9223"
[System.Diagnostics.Process]::Start($psi) | Out-Null
Start-Sleep -Seconds 10
Write-Output ("running: " + ((Get-Process tlbb-shell).Count))
$conns = Get-NetTCPConnection -LocalPort 9223
Write-Output ("port 9223 listeners: " + $conns.Count)
Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" | ForEach-Object {
  $cl = $_.CommandLine
  if ($cl -notmatch "tlbb-shell") { continue }; if ($cl.Length -gt 700) { $cl = $cl.Substring(0, 700) }
  Write-Output ("pid " + $_.ProcessId + " :: " + ($cl -replace "`r`n", " "))
}
try {
  $j = (Invoke-WebRequest -Uri "http://127.0.0.1:9223/json/version" -UseBasicParsing).Content
  Write-Output ("json/version: " + $j)
} catch {
  Write-Output ("fetch failed: " + $_.Exception.Message)
}
