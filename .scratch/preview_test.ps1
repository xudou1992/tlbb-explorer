Add-Type @'
using System;using System.Runtime.InteropServices;using System.Drawing;using System.Drawing.Imaging;
public class DR {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  public struct RECT { public int L, T, R, B; }
  public static void Click(IntPtr hwnd, int rx, int ry) {
    RECT r; GetWindowRect(hwnd, out r);
    SetCursorPos(r.L + rx, r.T + ry);
    System.Threading.Thread.Sleep(250);
    mouse_event(2, 0, 0, 0, UIntPtr.Zero);
    mouse_event(4, 0, 0, 0, UIntPtr.Zero);
  }
  public static void Type(IntPtr hwnd, string text) {
    SetCursorPos(0, 0);
    foreach (char ch in text) {
      short vk = VkKeyScan(ch);
      byte key = (byte)(vk & 0xff);
      keybd_event(key, 0, 0, UIntPtr.Zero);
      keybd_event(key, 0, 2, UIntPtr.Zero);
      System.Threading.Thread.Sleep(30);
    }
  }
  [DllImport("user32.dll")] public static extern short VkKeyScan(char ch);
  public static void Take(IntPtr hwnd, string path) {
    RECT r; GetWindowRect(hwnd, out r);
    Bitmap bmp = new Bitmap(r.R - r.L, r.B - r.T);
    Graphics g = Graphics.FromImage(bmp);
    IntPtr dc = g.GetHdc();
    PrintWindow(hwnd, dc, 2);
    g.ReleaseHdc(dc); g.Dispose();
    bmp.Save(path, ImageFormat.Png); bmp.Dispose();
  }
}
'@ -ReferencedAssemblies System.Drawing

$p = Get-Process tlbb-shell -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'no-window'; exit }

# 1. 搜索框（逻辑坐标 127,157）输入 w1351_nan_s_yifu_new_dingchunqiu
[DR]::Click($p.MainWindowHandle, 127, 157)
Start-Sleep -Milliseconds 500
[DR]::Type($p.MainWindowHandle, 'dingchunqiu')
Start-Sleep -Seconds 4
[DR]::Take($p.MainWindowHandle, 'D:/TLGL/.scratch/prev_1_search.png')

# 2. 点第一行结果
[DR]::Click($p.MainWindowHandle, 430, 205)
Start-Sleep -Seconds 8
[DR]::Take($p.MainWindowHandle, 'D:/TLGL/.scratch/prev_2_detail.png')

Write-Output 'search-done'
