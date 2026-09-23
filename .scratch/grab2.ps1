Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Collections.Generic;
public class Cap {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  public static List<IntPtr> ForPid(uint wanted) {
    var hits = new List<IntPtr>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == wanted && IsWindowVisible(h)) {
        var sb = new StringBuilder(512); GetWindowText(h, sb, 512);
        RECT r; GetWindowRect(h, out r);
        if (sb.Length > 3) hits.Add(h);
      }
      return true;
    }, IntPtr.Zero);
    return hits;
  }
  public static RECT Rect(IntPtr h) { RECT r; GetWindowRect(h, out r); return r; }
  public static void Grab(IntPtr h, string path) {
    ShowWindow(h, 9);   // SW_RESTORE: the window may have been minimised
    RECT r = Rect(h);
    int w = r.R - r.L, hh = r.B - r.T;
    var bmp = new System.Drawing.Bitmap(w, hh);
    using (var g = System.Drawing.Graphics.FromImage(bmp)) {
      IntPtr hdc = g.GetHdc();
      PrintWindow(h, hdc, 2);
      g.ReleaseHdc(hdc);
    }
    bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png);
    Console.WriteLine("grabbed " + w + "x" + hh + " -> " + path);
  }
}
"@
$procs = Get-Process tlbb-shell -ErrorAction SilentlyContinue
if (-not $procs) { Write-Output "tlbb-shell not running"; exit 1 }
foreach ($p in $procs) {
  foreach ($h in [Cap]::ForPid([uint32]$p.Id)) {
    Write-Output ("hwnd " + $h + " pid " + $p.Id)
    [Cap]::Grab($h, "D:\TLGL\.scratch\app-shot.png")
  }
}
