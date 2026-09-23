$ErrorActionPreference = "SilentlyContinue"
$out = @()
Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" | ForEach-Object {
  $cl = $_.CommandLine
  if ($null -ne $cl -and $cl.Contains("tlbb")) {
    $out += ("pid=" + $_.ProcessId + " | " + $cl)
  }
}
$out | Set-Content -Encoding UTF8 "D:\TLGL\.scratch\webview-cmds.txt"
Write-Output ("lines " + $out.Count)
