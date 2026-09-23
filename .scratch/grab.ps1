Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing,System.Drawing.Primitives @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Cap {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  public static IntPtr Find(uint pid) {
    IntPtr hit = IntPtr.Zero;
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      var sb = new StringBuilder(512); GetWindowText(h, sb, 512);
      if (p == pid && IsWindowVisible(h) && sb.Length > 3) {
        RECT r; GetWindowRect(h, out r);
        if (r.R - r.L > 300) { hit = h; return false; }
      }
      return true;
    }, IntPtr.Zero);
    return hit;
  }
  public static Bitmap Grab(IntPtr h, int w, int hh) {
    var bmp = new Bitmap(w, hh);
    using (var g = Graphics.FromImage(bmp)) {
      var hdc = g.GetHdc();
      PrintWindow(h, hdc, 2);   // PW_RENDERFULLCONTENT
      g.ReleaseHdc(hdc);
    }
    return bmp;
  }
}
"@
$ErrorActionPreference = "Stop"
$p = Get-Process tlbb-shell | Select-Object -First 1
if (-not $p) { Write-Output "tlbb-shell 未运行"; exit 1 }
$h = [Cap]::Find([uint32]$p.Id)
if ($h -eq [IntPtr]::Zero) { Write-Output "找不到窗口"; exit 1 }
$r = New-Object Cap+RECT
[Cap]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.R - $r.L; $hh = $r.B - $r.T
Write-Output ("window " + $w + "x" + $hh + " at " + $r.L + "," + $r.T)
$bmp = [Cap]::Grab($h, $w, $hh)
$bmp.Save("D:\TLGL\.scratch\app-shot.png", [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "saved app-shot.png"
