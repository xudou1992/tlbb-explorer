param([int]$Port = 9222)
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
  $w = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($w.ParentProcessId)"
  Write-Output ("端口 $Port 由 PID " + $w.ProcessId + " (" + $w.Name + ") 监听着，父进程 PID " + $w.ParentProcessId + " = " + $p.Name + " @ " + $p.ExecutablePath)
}
$shells = Get-CimInstance Win32_Process -Filter "Name='tlbb-shell.exe'"
if (-not $shells) { Write-Output "没有 tlbb-shell 在跑" }
foreach ($s in $shells) { Write-Output ("tlbb-shell PID " + $s.ProcessId + " 启动 " + $s.CreationDate + " 路径 " + $s.ExecutablePath) }
