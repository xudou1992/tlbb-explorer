Add-Type @'
using System;using System.Runtime.InteropServices;using System.Drawing;using System.Drawing.Imaging;
public class SC {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public struct RECT { public int L, T, R, B; }
  public static void Click(IntPtr hwnd, int rx, int ry) {
    RECT r; GetWindowRect(hwnd, out r);
    SetCursorPos(r.L + rx, r.T + ry);
    System.Threading.Thread.Sleep(300);
    mouse_event(2, 0, 0, 0, UIntPtr.Zero);
    mouse_event(4, 0, 0, 0, UIntPtr.Zero);
  }
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

[SC]::SetProcessDPIAware() | Out-Null

$p = Get-Process tlbb-shell -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'no-window'; exit }
[SC]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 900
$r = New-Object SC+RECT
[SC]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$w = $r.R - $r.L
Write-Output ("window physical w=" + $w)
# 物理位图约 1800 宽（DPI 125%）：按钮位图 x = 逻辑位图 x * (1800/1452)
$k = $w / 1452.0
$mapBtnX = [int](1320 * $k); $mapBtnY = [int](62 * $k)
$backX   = [int](1395 * $k); $backY   = [int](62 * $k)

# 步骤2：点顶栏「地图」
[SC]::Click($p.MainWindowHandle, $mapBtnX, $mapBtnY)
Start-Sleep -Seconds 10
[SC]::Take($p.MainWindowHandle, 'D:/TLGL/.scratch/step2_map.png')

# 步骤3：点地图列表第 3 行
[SC]::Click($p.MainWindowHandle, [int](190 * $k), [int](340 * $k))
Start-Sleep -Seconds 8
[SC]::Take($p.MainWindowHandle, 'D:/TLGL/.scratch/step3_switch.png')

# 步骤4：点「返回资产」
[SC]::Click($p.MainWindowHandle, $backX, $backY)
Start-Sleep -Seconds 4
[SC]::Take($p.MainWindowHandle, 'D:/TLGL/.scratch/step4_back.png')

# 步骤5：再次进地图
[SC]::Click($p.MainWindowHandle, $mapBtnX, $mapBtnY)
Start-Sleep -Seconds 8
[SC]::Take($p.MainWindowHandle, 'D:/TLGL/.scratch/step5_reenter.png')

Write-Output '4-steps-done'
