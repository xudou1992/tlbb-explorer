param([string]$Exe = "D:\TLGL\tlbb-explorer\app\src-tauri\target\release\tlbb-shell.exe",
      [int]$Port = 9222)
# 只清 tlbb-shell 自己的进程：msedgewebview2 是全机共用的，不能一把梭杀掉，
# 别的窗口（编辑器、浏览器）也挂在它上面。端口若被残留子进程占着就换一个。
Stop-Process -Name tlbb-shell -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$chosen = -1
foreach ($try in @($Port, $Port + 1, $Port + 2, $Port + 3)) {
  if (-not (Get-NetTCPConnection -LocalPort $try -State Listen -ErrorAction SilentlyContinue)) { $chosen = $try; break }
}
if ($chosen -lt 0) { Write-Output "$Port..$($Port+3) 全被占着，先手动看看谁在监听"; exit 1 }
if ($chosen -ne $Port) { Write-Output "端口 $Port 还被残留进程占着，本次改用 $chosen" }
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$chosen"
$p = Start-Process -FilePath $Exe -PassThru `
     -RedirectStandardError "D:\TLGL\.scratch\shell_err.txt" `
     -RedirectStandardOutput "D:\TLGL\.scratch\shell_out.txt"
Start-Sleep -Seconds 14
$s = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)"
if (-not $s) {
  Write-Output "新起的 PID $($p.Id) 自己退出去了，stderr 前几行："
  Get-Content "D:\TLGL\.scratch\shell_err.txt" -TotalCount 6
  exit 1
}
Write-Output ("PORT=" + $chosen)
Write-Output ("在跑的是 PID " + $p.Id + " ← " + $s.ExecutablePath)
Write-Output ("exe 构建时间 " + (Get-Item $Exe).LastWriteTime)
