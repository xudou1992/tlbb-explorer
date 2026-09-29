$exe = "D:\TLGL\.scratch\rc3\release\tlbb-shell.exe"
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 10
if ($p.HasExited) {
  Write-Output "进程提前退出，退出码 $($p.ExitCode)"
  exit 1
}
Write-Output "PID $($p.Id)"
& "D:\TLGL\.scratch\printwin.ps1" -TargetPid $p.Id -Out "D:/TLGL/.scratch/ui_check/skel_round.png"
Write-Output "captured"
