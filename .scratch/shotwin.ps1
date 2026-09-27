param([int]$TargetPid, [string]$Out = "D:/TLGL/.scratch/app_shot.png", [int]$WaitMs = 0)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class PW4 {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
$script:h = [IntPtr]::Zero
$cb = [PW4+EnumProc]{
  param($w,$lp)
  $procId = [uint32]0
  [void][PW4]::GetWindowThreadProcessId($w, [ref]$procId)
  if ([int]$procId -eq $TargetPid -and [PW4]::IsWindowVisible($w)) {
    $r = New-Object PW4+RECT
    [void][PW4]::GetWindowRect($w, [ref]$r)
    if (($r.R - $r.L) -gt 300) { $script:h = $w }
  }
  return $true
}
[void][PW4]::EnumWindows($cb, [IntPtr]::Zero)
if ($script:h -eq [IntPtr]::Zero) { "NO_WINDOW" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt; exit 1 }
$rr = New-Object PW4+RECT
[void][PW4]::GetWindowRect($script:h, [ref]$rr)
if ($WaitMs -gt 0) { Start-Sleep -Milliseconds $WaitMs }
$w = $rr.R - $rr.L; $hh = $rr.B - $rr.T
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[void][PW4]::PrintWindow($script:h, $hdc, 2)
$g.ReleaseHdc($hdc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"SHOT ${w}x${hh} rect $($rr.L),$($rr.T),$($rr.R),$($rr.B) -> $Out" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt
