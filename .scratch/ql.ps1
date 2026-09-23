$ErrorActionPreference = "SilentlyContinue"
Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" | ForEach-Object {
  $cl = $_.CommandLine
  if ($cl -match "tlbb-shell" -and $cl -notmatch "--type=") {
    Write-Output ("BROWSER pid " + $_.ProcessId)
    Write-Output $cl
  }
}
Write-Output "--- ports"
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -ge 9220 -and $_.LocalPort -le 9230 } | ForEach-Object { Write-Output ($_.LocalAddress + ":" + $_.LocalPort) }
Write-Output "--- done"
