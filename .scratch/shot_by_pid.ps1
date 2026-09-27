param([int]$TargetPid = 0, [string]$Out = "D:\TLGL\.scratch\shot.png")
Add-Type -AssemblyName System.Drawing
if (-not ('PW' -as [type])) {
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class RECT2 { public int L; public int T; public int R; public int B; }
public class PW {
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT2 r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
}
'@
}
$found = [IntPtr]::Zero
$cb = [PW+EnumWindowsProc] {
  param($h, $l)
  $p = 0
  [void][PW]::GetWindowThreadProcessId($h, [ref]$p)
  if ($p -eq $TargetPid -and [PW]::IsWindowVisible($h) -and [PW]::GetWindowTextLength($h) -gt 3) {
    $r = New-Object RECT2
    [void][PW]::GetWindowRect($h, [ref]$r)
    if (($r.R - $r.L) -gt 400) { $script:found = $h }
  }
  return $true
}
[void][PW]::EnumWindows($cb, [IntPtr]::Zero)
if ($found -eq [IntPtr]::Zero) { Write-Output "no-window"; exit 1 }
$rect = New-Object RECT2
[void][PW]::GetWindowRect($found, [ref]$rect)
Write-Output ("hwnd=" + $found + " rect=" + $rect.L + "," + $rect.T + "," + $rect.R + "," + $rect.B)
if ($rect.L -lt -10000) {
  [void][PW]::ShowWindow($found, 9)
  [void][PW]::SetForegroundWindow($found)
  Start-Sleep -Milliseconds 900
  [void][PW]::GetWindowRect($found, [ref]$rect)
  Write-Output ("restored rect=" + $rect.L + "," + $rect.T + "," + $rect.R + "," + $rect.B)
}
$w = $rect.R - $rect.L
$h = $rect.B - $rect.T
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
[void][PW]::PrintWindow($found, $dc, 2)
$g.ReleaseHdc($dc)
$g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output ("saved " + $Out)
