# 用 PrintWindow 直接抓 tlbb-shell 窗口内容:不抢前台、不动窗口、不截别的。
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinP {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int L; public int T; public int R; public int B; }
}
"@
$log = "D:\TLGL\.scratch\shot_win3.log"
try {
  $p = Get-Process tlbb-shell | Select-Object -First 1
  $h = $p.MainWindowHandle
  $r = New-Object WinP+RECT
  [WinP]::GetWindowRect($h, [ref]$r) | Out-Null
  $w = $r.R - $r.L
  $ht = $r.B - $r.T
  $bmp = New-Object System.Drawing.Bitmap $w, $ht
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  # PW_RENDERFULLCONTENT = 2:连 WebView2 这类硬件合成内容也能抓
  [WinP]::PrintWindow($h, $hdc, 2) | Out-Null
  $g.ReleaseHdc($hdc)
  $bmp.Save("D:\TLGL\.scratch\browse_shot3.png", [System.Drawing.Imaging.ImageFormat]::Png)
  Set-Content -Path $log -Value "OK w=$w h=$ht" -Encoding UTF8
} catch {
  Set-Content -Path $log -Value "ERR $_" -Encoding UTF8
}
