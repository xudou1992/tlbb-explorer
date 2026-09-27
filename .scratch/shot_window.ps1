$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  public delegate bool EnumProc(IntPtr h, IntPtr lp);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
$out = "D:\TLGL\.scratch\window_shot.png"
$want = "D:\TLGL\.scratch\window_list.txt"
$lines = @()
$target = [IntPtr]::Zero
$cb = [W+EnumProc] {
  param($h, $lp)
  $len = [W]::GetWindowTextLength($h)
  if ($len -gt 0 -and [W]::IsWindowVisible($h)) {
    $sb = New-Object System.Text.StringBuilder ($len + 2)
    [void][W]::GetWindowText($h, $sb, $sb.Capacity)
    $t = $sb.ToString()
    $procId = 0
    [void][W]::GetWindowThreadProcessId($h, [ref]$procId)
    $r = New-Object W+RECT
    [void][W]::GetWindowRect($h, [ref]$r)
    $script:lines += ("{0} | pid={1} | {2}x{3} | {4}" -f $h, $procId, ($r.R - $r.L), ($r.B - $r.T), $t)
    if ($t -like "*资源浏览器*" -or $t -like "*资产台*" -or $t -like "*TLBB*") { $script:target = $h }
  }
  return $true
}
[void][W]::EnumWindows($cb, [IntPtr]::Zero)
Set-Content -Path $want -Value $lines -Encoding UTF8
if ($target -ne [IntPtr]::Zero) {
  [void][W]::SetForegroundWindow($target)
  Start-Sleep -Milliseconds 900
  $r = New-Object W+RECT
  [void][W]::GetWindowRect($target, [ref]$r)
  $w = $r.R - $r.L; $h = $r.B - $r.T
  $bmp = New-Object System.Drawing.Bitmap $w, $h
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size $w, $h))
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  "OK $out $w x $h" | Out-File -Encoding ascii D:\TLGL\.scratch\window_shot_status.txt
} else {
  "NO_TARGET" | Out-File -Encoding ascii D:\TLGL\.scratch\window_shot_status.txt
}
