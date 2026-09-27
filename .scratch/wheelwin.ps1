param([int]$TargetPid,[int]$X,[int]$Y,[int]$Notches=30,[string]$Out="D:/TLGL/.scratch/app_wheel.png",[int]$WaitMs=2500)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class PW5 {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, int data, UIntPtr extra);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
$script:h=[IntPtr]::Zero
$cb=[PW5+EnumProc]{param($w,$lp)
 $procId=[uint32]0
 [void][PW5]::GetWindowThreadProcessId($w,[ref]$procId)
 if([int]$procId -eq $TargetPid -and [PW5]::IsWindowVisible($w)){
   $r=New-Object PW5+RECT; [void][PW5]::GetWindowRect($w,[ref]$r)
   if(($r.R-$r.L) -gt 300){ $script:h=$w }
 }
 return $true}
[void][PW5]::EnumWindows($cb,[IntPtr]::Zero)
if($script:h -eq [IntPtr]::Zero){ "NO_WINDOW" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt; exit 1 }
$rr=New-Object PW5+RECT; [void][PW5]::GetWindowRect($script:h,[ref]$rr)
$ax=$rr.L+$X; $ay=$rr.T+$Y
[void][PW5]::SetForegroundWindow($script:h)
Start-Sleep -Milliseconds 300
[void][PW5]::SetCursorPos($ax,$ay)
Start-Sleep -Milliseconds 200
for($i=0; $i -lt $Notches; $i++){
  [PW5]::mouse_event(0x0800,0,0,-120,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 30
}
Start-Sleep -Milliseconds $WaitMs
$w=$rr.R-$rr.L; $hh=$rr.B-$rr.T
$bmp=New-Object System.Drawing.Bitmap $w,$hh
$g=[System.Drawing.Graphics]::FromImage($bmp)
$hdc=$g.GetHdc()
[void][PW5]::PrintWindow($script:h,$hdc,2)
$g.ReleaseHdc($hdc)
$bmp.Save($Out,[System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose();$bmp.Dispose()
"WHEEL ${Notches} down at ${ax},${ay} -> $Out" | Out-File -Encoding ascii D:\TLGL\.scratch\click_status.txt
