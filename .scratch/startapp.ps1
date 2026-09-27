param(
  [string]$Exe = "D:\TLGL\tlbb-explorer\app\src-tauri\target\debug\tlbb-shell.exe",
  [string]$Dir = "D:\TLGL",
  [string]$Err = "D:\TLGL\.scratch\app_stderr.log",
  [string]$Out = "D:\TLGL\.scratch\app_stdout.log"
)
$p = Start-Process -FilePath $Exe -WorkingDirectory $Dir -RedirectStandardError $Err -RedirectStandardOutput $Out -PassThru
$p.Id | Out-File -Encoding ascii D:\TLGL\.scratch\app_pid.txt
"PID $($p.Id)"
