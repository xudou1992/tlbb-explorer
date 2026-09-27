param([int]$TargetPid,[int]$X,[int]$Y,[string]$Out="D:/TLGL/.scratch/app_click.png",[int]$WaitMs=1500)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class PW3 {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
 [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X,Y; }
}
"@
$script:h=[IntPtr]::Zero
$cb=[PW3+EnumProc]{param($w,$lp)
 $procId=[uint32]0
 [void][PW3]::GetWindowThreadProcessId($w,[ref]$procId)
 if([int]$procId -eq $TargetPid -and [PW3]::IsWindowVisible($w)){
   $r=New-Object PW3+RECT; [void][PW3]::GetWindowRect($w,[ref]$r)
   if(($r.R-$r.L) -gt 300){ $script:h=$w }
 }
 return $true}
[void][PW3]::EnumWindows($cb,[IntPtr]::Zero)
if($script:h -eq [IntPtr]::Zero){ "NO_WINDOW" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt; exit 1 }
$rr=New-Object PW3+RECT; [void][PW3]::GetWindowRect($script:h,[ref]$rr)
"rect $($rr.L),$($rr.T),$($rr.R),$($rr.B)" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt -Append
$ax=$rr.L+$X; $ay=$rr.T+$Y
$fg=[PW3]::SetForegroundWindow($script:h)
Start-Sleep -Milliseconds 400
$sc=[PW3]::SetCursorPos($ax,$ay)
Start-Sleep -Milliseconds 200
$pt=New-Object PW3+POINT
$gc=[PW3]::GetCursorPos([ref]$pt)
$hw=[PW3]::WindowFromPoint($pt)
$hwpid=[uint32]0
[void][PW3]::GetWindowThreadProcessId($hw,[ref]$hwpid)
$wfp = $hw
"fg=$fg setcursor=$sc getcursor=$gc pos=$($pt.X),$($pt.Y) expect=$ax,$ay hwndAtPoint=$hw pidAtPoint=$hwpid mainHwnd=$($script:h)" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt -Append
[PW3]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
Start-Sleep -Milliseconds 80
[PW3]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
Start-Sleep -Milliseconds $WaitMs
$w=$rr.R-$rr.L; $hh=$rr.B-$rr.T
$bmp=New-Object System.Drawing.Bitmap $w,$hh
$g=[System.Drawing.Graphics]::FromImage($bmp)
$hdc=$g.GetHdc()
[void][PW3]::PrintWindow($script:h,$hdc,2)
$g.ReleaseHdc($hdc)
$bmp.Save($Out,[System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose();$bmp.Dispose()
"CLICK ${ax},${ay} -> $Out" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt -Append
