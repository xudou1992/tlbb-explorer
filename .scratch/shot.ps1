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
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  public static System.Collections.Generic.List<IntPtr> Find(string pidWanted) {
    var hits = new System.Collections.Generic.List<IntPtr>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (IsWindowVisible(h) && pid.ToString() == pidWanted) {
        var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
        if (sb.Length > 0) hits.Add(h);
      }
      return true;
    }, IntPtr.Zero);
    return hits;
  }
}
"@
$procs = Get-Process tlbb-shell -ErrorAction SilentlyContinue
if (-not $procs) { Write-Output "no tlbb-shell process"; exit 1 }
foreach ($p in $procs) {
  foreach ($h in [W]::Find($p.Id.ToString())) {
    Write-Output ("window pid=" + $p.Id + " hwnd=" + $h)
    [W]::ShowWindow($h, 9) | Out-Null   # 9 = restore
    [W]::SetForegroundWindow($h) | Out-Null
  }
}
Start-Sleep -Milliseconds 1200
$sc = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b = New-Object System.Drawing.Bitmap $sc.Width, $sc.Height
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen(0, 0, 0, 0, $b.Size)
$b.Save("D:\TLGL\.scratch\shot.png", [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output ("saved " + $sc.Width + "x" + $sc.Height)
