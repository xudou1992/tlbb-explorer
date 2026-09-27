param([int]$TargetPid=29660,[string]$Out="D:\TLGL\.scratch\app_shot.png")
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class W2 {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
$script:found=[IntPtr]::Zero
$cb=[W2+EnumProc]{param($h,$lp)
  $procId=[uint32]0
  [void][W2]::GetWindowThreadProcessId($h,[ref]$procId)
  if([int]$procId -eq $TargetPid -and [W2]::IsWindowVisible($h)){
    $r=New-Object W2+RECT
    [void][W2]::GetWindowRect($h,[ref]$r)
    if(($r.R-$r.L) -gt 200){ $script:found=$h }
  }
  return $true}
[void][W2]::EnumWindows($cb,[IntPtr]::Zero)
if($script:found -eq [IntPtr]::Zero){"NO_WINDOW" | Out-File -Encoding ascii D:\TLGL\.scratch\app_shot_status.txt; exit}
[void][W2]::ShowWindow($script:found,9)
[void][W2]::SetForegroundWindow($script:found)
Start-Sleep -Milliseconds 1200
$rr=New-Object W2+RECT
[void][W2]::GetWindowRect($script:found,[ref]$rr)
$w=$rr.R-$rr.L
$h=$rr.B-$rr.T
$bmp=New-Object System.Drawing.Bitmap $w,$h
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rr.L,$rr.T,0,0,(New-Object System.Drawing.Size $w,$h))
$bmp.Save($Out,[System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
"OK $Out ${w}x${h}" | Out-File -Encoding ascii D:\TLGL\.scratch\app_shot_status.txt
