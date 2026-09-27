param([int]$TargetPid=29660,[string]$Out="D:/TLGL/.scratch/app_printwin.png")
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class PW {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
$script:h=[IntPtr]::Zero
$cb=[PW+EnumProc]{param($w,$lp)
 $procId=[uint32]0
 [void][PW]::GetWindowThreadProcessId($w,[ref]$procId)
 if([int]$procId -eq $TargetPid -and [PW]::IsWindowVisible($w)){
   $r=New-Object PW+RECT; [void][PW]::GetWindowRect($w,[ref]$r)
   if(($r.R-$r.L) -gt 300){ $script:h=$w }
 }
 return $true}
[void][PW]::EnumWindows($cb,[IntPtr]::Zero)
if($script:h -eq [IntPtr]::Zero){ "NO_WINDOW" | Out-File -Encoding ascii D:\TLGL\.scratch\printwin_status.txt; exit }
$rr=New-Object PW+RECT; [void][PW]::GetWindowRect($script:h,[ref]$rr)
$w=$rr.R-$rr.L; $hh=$rr.B-$rr.T
$bmp=New-Object System.Drawing.Bitmap $w,$hh
$g=[System.Drawing.Graphics]::FromImage($bmp)
$hdc=$g.GetHdc()
[void][PW]::PrintWindow($script:h,$hdc,2)
$g.ReleaseHdc($hdc)
$bmp.Save($Out,[System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose();$bmp.Dispose()
"OK $Out ${w}x${hh}" | Out-File -Encoding ascii D:\TLGL\.scratch\printwin_status.txt
