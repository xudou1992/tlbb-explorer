param(
  [int]$TargetPid,
  [int]$Hwnd = 0,
  [string]$Key = "ESC",
  [string]$Out = "D:/TLGL/.scratch/keywin.png",
  [int]$WaitMs = 1500
)
# Send one key to the target window (needs focus), then screenshot.
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class KW {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
}
'@
$p = Get-Process -Id $TargetPid -ErrorAction Stop
if ($Hwnd -gt 0) { $h = [IntPtr]$Hwnd } else { $h = [IntPtr]$p.MainWindowHandle }
[void][KW]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 400
$vk = 0x1B  # ESC
[KW]::keybd_event($vk, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 60
[KW]::keybd_event($vk, 0, 2, [UIntPtr]::Zero)
Start-Sleep -Milliseconds $WaitMs
# screenshot
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Drawing;
using System.Drawing.Imaging;
public class PS2 {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
'@
$r = New-Object PS2+RECT
[void][PS2]::GetWindowRect($h, [ref]$r)
$w = $r.R - $r.L; $ht = $r.B - $r.T
if ($w -le 0 -or $ht -le 0) { "window gone"; exit 1 }
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
[void][PS2]::PrintWindow($h, $dc, 2)
$g.ReleaseHdc($dc); $g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
"KEY $Key -> $Out ($w x $ht)"
