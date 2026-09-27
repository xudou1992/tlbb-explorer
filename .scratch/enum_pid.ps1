param([int]$TargetPid)
Add-Type @"
using System;using System.Runtime.InteropServices;using System.Text;
public class EW {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
 public delegate bool EnumProc(IntPtr h, IntPtr lp);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
$cb = [EW+EnumProc]{
  param($w,$lp)
  $procId = [uint32]0
  [void][EW]::GetWindowThreadProcessId($w, [ref]$procId)
  if ([int]$procId -eq $TargetPid) {
    $r = New-Object EW+RECT
    [void][EW]::GetWindowRect($w, [ref]$r)
    $sb = New-Object System.Text.StringBuilder 256
    [void][EW]::GetWindowTextW($w, $sb, 256)
    Write-Output ("hwnd=$w vis=" + [EW]::IsWindowVisible($w) + " min=" + [EW]::IsIconic($w) + " rect=" + $r.L + "," + $r.T + "," + $r.R + "," + $r.B + " len=" + $sb.Length)
  }
  return $true
}
[void][EW]::EnumWindows($cb, [IntPtr]::Zero)
