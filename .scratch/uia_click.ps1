param([int]$TargetPid, [string]$Text, [switch]$Click)
Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $TargetPid)
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
if ($wins.Count -eq 0) { "NO_WINDOW" | Out-File -Encoding ascii D:\TLGL\.scratch\uia_status.txt; exit 1 }
$btnCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $Text)
$btn = $wins.Item(0).FindFirst([System.Windows.Automation.TreeScope]::Descendants, $btnCond)
if (-not $btn) {
  $names = $wins.Item(0).FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object { $_.Current.Name } | Where-Object { $_ } | Select-Object -First 60
  ("NOT_FOUND; names: " + ($names -join " | ")) | Out-File -Encoding ascii D:\TLGL\.scratch\uia_status.txt
  exit 2
}
$r = $btn.Current.BoundingRectangle
if ($Click) {
  Add-Type @"
using System;using System.Runtime.InteropServices;
public class PW3 {
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
}
"@
  [void][PW3]::SetForegroundWindow($wins.Item(0).Current.NativeWindowHandle)
  Start-Sleep -Milliseconds 200
  $ax = [int](($r.Left + $r.Right) / 2); $ay = [int](($r.Top + $r.Bottom) / 2)
  [void][PW3]::SetCursorPos($ax, $ay)
  Start-Sleep -Milliseconds 120
  [PW3]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 50
  [PW3]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 1500
}
("FOUND " + $r.Left + "," + $r.Top + " - " + $r.Right + "," + $r.Bottom) | Out-File -Encoding ascii D:\TLGL\.scratch\uia_status.txt
