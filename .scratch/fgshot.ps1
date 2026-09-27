param([int]$TargetPid, [string]$Out = "D:\TLGL\.scratch\fg.png", [switch]$Esc)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class FG {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
 [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
$script:h = [IntPtr]::Zero
$cb = [FG+EnumProc]{param($w,$lp)
  $procId = [uint32]0
  [void][FG]::GetWindowThreadProcessId($w, [ref]$procId)
  if ([int]$procId -eq $TargetPid -and [FG]::IsWindowVisible($w)) {
    $r = New-Object FG+RECT; [void][FG]::GetWindowRect($w, [ref]$r)
    if (($r.R - $r.L) -gt 300) { $script:h = $w }
  }
  return $true}
[void][FG]::EnumWindows($cb, [IntPtr]::Zero)
if ($script:h -eq [IntPtr]::Zero) { "NO_WINDOW" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt; exit 1 }
[void][FG]::ShowWindow($script:h, 9)
[void][FG]::SetForegroundWindow($script:h)
Start-Sleep -Milliseconds 1500
if ($Esc) {
  [void][FG]::SetForegroundWindow($script:h)
  Start-Sleep -Milliseconds 300
  [FG]::keybd_event(0x1B, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 60
  [FG]::keybd_event(0x1B, 0, 2, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 2000
}
$rr = New-Object FG+RECT; [void][FG]::GetWindowRect($script:h, [ref]$rr)
$w = $rr.R - $rr.L; $hh = $rr.B - $rr.T
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[void][FG]::PrintWindow($script:h, $hdc, 2)
$g.ReleaseHdc($hdc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"FG hwnd=$($script:h) ${w}x${hh} -> $Out" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt
