param([string]$Img = "D:\TLGL\.scratch\t8_real.png")
Add-Type -AssemblyName System.Drawing
$bmp = [System.Drawing.Bitmap]::FromFile($Img)
$border = 0
$bg = 0
$cols = New-Object System.Collections.Generic.HashSet[int]
for ($y = 120; $y -lt 930; $y++) {
  for ($x = 0; $x -lt 1456; $x++) {
    $c = $bmp.GetPixel($x, $y)
    if ([Math]::Abs($c.R - 36) -le 8 -and [Math]::Abs($c.G - 51) -le 8 -and [Math]::Abs($c.B - 60) -le 8) {
      $border++
      [void]$cols.Add($x)
    }
    if ([Math]::Abs($c.R - 14) -le 4 -and [Math]::Abs($c.G - 20) -le 4 -and [Math]::Abs($c.B - 23) -le 4) { $bg++ }
  }
}
Write-Output ("border_px=$border bg_px=$bg distinct_x=" + $cols.Count)
$xs = $cols | Sort-Object
if ($xs.Count -gt 0) {
  $min = $xs[0]; $max = $xs[$xs.Count - 1]
  Write-Output ("x_range=$min..$max")
  $runs = New-Object System.Collections.ArrayList
  $start = -1; $prev = -999
  foreach ($x in $xs) {
    if ($x - $prev -gt 3) {
      if ($start -ge 0) { [void]$runs.Add("$start..$prev") }
      $start = $x
    }
    $prev = $x
  }
  [void]$runs.Add("$start..$prev")
  Write-Output ("runs: " + ($runs -join " | "))
}
$bmp.Dispose()
