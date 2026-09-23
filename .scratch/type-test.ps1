Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type -ReferencedAssemblies System.Drawing @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Collections.Generic;
public class Ui {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint d, uint e, uint extra, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  public static List<IntPtr> ForPid(uint wanted) {
    var hits = new List<IntPtr>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == wanted) {
        var sb = new StringBuilder(512); GetWindowText(h, sb, 512);
        if (sb.Length > 3) hits.Add(h);
      }
      return true;
    }, IntPtr.Zero);
    return hits;
  }
  public static RECT Rect(IntPtr h) { RECT r; GetWindowRect(h, out r); return r; }
  public static void Click(int x, int y) {
    SetCursorPos(x, y);
    mouse_event(0x0002, 0, 0, 0, IntPtr.Zero);
    mouse_event(0x0004, 0, 0, 0, IntPtr.Zero);
  }
  public static void Grab(IntPtr h, string path) {
    RECT r = Rect(h);
    var bmp = new System.Drawing.Bitmap(r.R - r.L, r.B - r.T);
    using (var g = System.Drawing.Graphics.FromImage(bmp)) {
      IntPtr hdc = g.GetHdc();
      PrintWindow(h, hdc, 2);
      g.ReleaseHdc(hdc);
    }
    bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png);
    Console.WriteLine("saved " + path);
  }
}
"@
$p = Get-Process tlbb-shell | Select-Object -First 1
$h = ([Ui]::ForPid([uint32]$p.Id))[0]
[Ui]::ShowWindow($h, 9) | Out-Null
[Ui]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 800
$r = [Ui]::Rect($h)
Write-Output ("window at " + $r.L + "," + $r.T + " size " + ($r.R - $r.L) + "x" + ($r.B - $r.T))
# 1) click the search box (client 130,155; title bar ~31px)
[Ui]::Click(($r.L + 130), ($r.T + 31 + 155))
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait("^a")
[System.Windows.Forms.SendKeys]::SendWait([string]([char]0x66F3) + [string]([char]0x971C))   # caoshuang in Chinese
Start-Sleep -Seconds 4
[Ui]::Grab($h, "D:\TLGL\.scratch\search-caoshuang.png")
# 2) click the first card to load the evidence pane
$r2 = [Ui]::Rect($h)
[Ui]::Click(($r2.L + 480), ($r2.T + 31 + 300))
Start-Sleep -Seconds 3
[Ui]::Grab($h, "D:\TLGL\.scratch\detail.png")
