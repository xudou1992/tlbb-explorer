# 只截 tlbb-shell 主窗口:先唤到前台,再按窗口矩形截屏。输出走 UTF-8 文件。
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  public struct RECT { public int L; public int T; public int R; public int B; }
}
"@
$log = "D:\TLGL\.scratch\shot_win2.log"
try {
  $p = Get-Process tlbb-shell | Select-Object -First 1
  $h = $p.MainWindowHandle
  [Win]::ShowWindow($h, 9) | Out-Null
  [Win]::SetForegroundWindow($h) | Out-Null
  Start-Sleep -Milliseconds 900
  $r = New-Object Win+RECT
  [Win]::GetWindowRect($h, [ref]$r) | Out-Null
  $w = $r.R - $r.L
  $ht = $r.B - $r.T
  $bmp = New-Object System.Drawing.Bitmap $w, $ht
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
  $bmp.Save("D:\TLGL\.scratch\browse_shot2.png", [System.Drawing.Imaging.ImageFormat]::Png)
  Set-Content -Path $log -Value "SHOT w=$w h=$ht rect=$($r.L),$($r.T),$($r.R),$($r.B)" -Encoding UTF8
} catch {
  Set-Content -Path $log -Value "ERR $_" -Encoding UTF8
}
