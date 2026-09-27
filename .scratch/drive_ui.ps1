# Acceptance driver v4, phased:
#   prep : HOME-reset page scroll, click reset-filters, paste query, wait, screenshot prep.png
#   pick : click first/second result row, settle, wheel detail pane, screenshot Out
param(
  [string]$Phase = "prep",
  [string]$Query = "w1351_boss_caoshuang",
  [string]$Out = "D:\TLGL\.scratch\accept_ui.png",
  [string]$PrepOut = "D:\TLGL\.scratch\prep_ui.png",
  [int]$RowY = 155,
  [int]$RowX = 420,
  [int]$Settle = 10
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, int dwData, UIntPtr dwExtraInfo);
  public struct RECT { public int L, T, R, B; }
}
"@

function Click-At([int]$x, [int]$y) {
  [Win]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 150
  [Win]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 60
  [Win]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 300
}

function Wheel-At([int]$x, [int]$y, [int]$delta) {
  [Win]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 200
  [Win]::mouse_event(0x0800, 0, 0, $delta, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 600
}

function Save-Shot([IntPtr]$h, [Win+RECT]$rect, [string]$path) {
  $bmp = New-Object System.Drawing.Bitmap(($rect.R - $rect.L), ($rect.B - $rect.T))
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  [Win]::PrintWindow($h, $hdc, 2) | Out-Null
  $g.ReleaseHdc($hdc); $g.Dispose()
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output "SAVED $path"
}

$p = Get-Process tlbb-shell -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
$h = $p.MainWindowHandle
[Win]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 500

$rect = New-Object Win+RECT
[Win]::GetWindowRect($h, [ref]$rect) | Out-Null

if ($Phase -eq "prep") {
  # force document scroll to top: click the footer strip (no input there), then HOME
  Click-At ($rect.L + 700) ($rect.T + 913)
  [System.Windows.Forms.SendKeys]::SendWait("{HOME}")
  Start-Sleep -Milliseconds 800
  # reset filters first (it also clears the query), then paste the query back
  Click-At ($rect.L + 514) ($rect.T + 123)
  Start-Sleep -Milliseconds 900
  # focus search, select-all, paste
  Click-At ($rect.L + 125) ($rect.T + 158)
  [System.Windows.Forms.SendKeys]::SendWait("^a")
  Set-Clipboard -Value $Query
  Start-Sleep -Milliseconds 200
  [System.Windows.Forms.SendKeys]::SendWait("^v")
  Start-Sleep -Milliseconds 2000
  Save-Shot $h $rect $PrepOut
}
elseif ($Phase -eq "pick") {
  Click-At ($rect.L + $RowX) ($rect.T + $RowY)
  Start-Sleep -Seconds $Settle
  Wheel-At ($rect.L + 1000) ($rect.T + 500) (-300)
  Wheel-At ($rect.L + 1000) ($rect.T + 500) (-300)
  Start-Sleep -Milliseconds 800
  Save-Shot $h $rect $Out
}
elseif ($Phase -eq "shot") {
  # page back to top, then plain screenshot (detail pane top: secAbs/secTex)
  Click-At ($rect.L + 700) ($rect.T + 913)
  [System.Windows.Forms.SendKeys]::SendWait("{HOME}")
  Start-Sleep -Milliseconds 1000
  Save-Shot $h $rect $Out
}
elseif ($Phase -eq "trytex") {
  # scroll detail pane down to the candidate cards, click the first "try" button,
  # then scroll back up to show the 3D stage with the texture applied
  Wheel-At ($rect.L + 1000) ($rect.T + 500) (-300)
  Wheel-At ($rect.L + 1000) ($rect.T + 500) (-300)
  Start-Sleep -Milliseconds 800
  Click-At ($rect.L + 679) ($rect.T + 441)      # card 1 "try on" button
  Start-Sleep -Seconds 2
  Wheel-At ($rect.L + 1000) ($rect.T + 400) (-800)
  Wheel-At ($rect.L + 1000) ($rect.T + 400) (-800)
  Start-Sleep -Milliseconds 800
  Save-Shot $h $rect $Out
}
