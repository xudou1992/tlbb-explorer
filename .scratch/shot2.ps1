Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  public static System.Collections.Generic.List<IntPtr> ForPid(uint wanted) {
    var hits = new System.Collections.Generic.List<IntPtr>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == wanted) hits.Add(h);
      return true;
    }, IntPtr.Zero);
    return hits;
  }
  public static string Title(IntPtr h) { var sb = new StringBuilder(512); GetWindowText(h, sb, 512); return sb.ToString(); }
}
"@
$procs = Get-Process tlbb-shell -ErrorAction SilentlyContinue
if (-not $procs) { Write-Output "no tlbb-shell process"; exit 1 }
$target = $null
foreach ($p in $procs) {
  foreach ($h in [W]::ForPid([uint32]$p.Id)) {
    $t = [W]::Title($h)
    $r = New-Object W+RECT
    [W]::GetWindowRect($h, [ref]$r) | Out-Null
    Write-Output ("hwnd=" + $h + " vis=" + [W]::IsWindowVisible($h) + " rect=" + $r.L + "," + $r.T + "," + $r.R + "," + $r.B + " title=[" + $t + "]")
    if ($t.Length -gt 0 -and $r.R -gt 200) { $target = $h }
  }
}
if (-not $target) { Write-Output "no candidate window"; exit 1 }
[W]::ShowWindow($target, 5) | Out-Null          # SW_SHOW
# 4 = HWND_TOPMOST, 0x0040 = SHOWWINDOW
[W]::SetWindowPos($target, [IntPtr](-1), 40, 30, 1500, 940, 0x0040) | Out-Null
[W]::SetForegroundWindow($target) | Out-Null
Start-Sleep -Milliseconds 1500
$sc = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b = New-Object System.Drawing.Bitmap $sc.Width, $sc.Height
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen(0, 0, 0, 0, $b.Size)
$b.Save("D:\TLGL\.scratch\shot.png", [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "saved"
