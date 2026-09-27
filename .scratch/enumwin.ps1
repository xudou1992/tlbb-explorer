param([int]$TargetPid = 37424)
Add-Type @"
using System;using System.Runtime.InteropServices;
public class W4 {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
 [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Rr,B; }
}
"@
$script:rows = New-Object System.Collections.ArrayList
$cb = [W4+EnumProc]{
  param($w,$lp)
  $p = [uint32]0
  [void][W4]::GetWindowThreadProcessId($w, [ref]$p)
  if ([int]$p -eq $TargetPid) {
    $r = New-Object W4+R
    [void][W4]::GetWindowRect($w, [ref]$r)
    $sb = New-Object System.Text.StringBuilder 256
    [void][W4]::GetWindowText($w, $sb, 256)
    [void]$script:rows.Add("hwnd=$w vis=$([W4]::IsWindowVisible($w)) min=$([W4]::IsIconic($w)) rect=$($r.L),$($r.T),$($r.Rr),$($r.B) title=$($sb.ToString())")
  }
  return $true
}
[void][W4]::EnumWindows($cb, [IntPtr]::Zero)
"--- windows of PID $TargetPid ---"
$script:rows
"--- process ---"
Get-Process -Id $TargetPid -ErrorAction SilentlyContinue | Format-List Id, Responding, MainWindowTitle, MainWindowHandle
