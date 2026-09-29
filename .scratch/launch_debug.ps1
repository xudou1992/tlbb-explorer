Stop-Process -Name tlbb-shell -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222"
$p = Start-Process -FilePath "D:\TLGL\.scratch\rc3\release\tlbb-shell.exe" -PassThru
Start-Sleep -Seconds 12
Write-Output "PID $($p.Id)"
