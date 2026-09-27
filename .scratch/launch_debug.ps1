# 带 WebView2 远程调试端口启动 tlbb-shell,用于自动化审计界面交互。
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = '--remote-debugging-port=9222'
Start-Process -FilePath 'D:\TLGL\tlbb-explorer\app\src-tauri\target\release\tlbb-shell.exe'
Write-Host 'LAUNCHED'
