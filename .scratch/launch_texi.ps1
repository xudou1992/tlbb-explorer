$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = '--remote-debugging-port=9223'
$p = Start-Process -FilePath 'D:/TLGL/.scratch/rc3/debug/tlbb-shell.exe' -PassThru
Write-Output ("pid " + $p.Id)
