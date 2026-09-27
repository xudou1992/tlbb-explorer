param(
  [string]$Img = "D:/TLGL/.scratch/app_map2.png",
  [int]$X0 = 0,
  [int]$X1 = 500,
  [int]$Y0 = 0,
  [int]$Y1 = 938
)
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap $Img
"VERSION-3 W=$($bmp.Width) H=$($bmp.Height)"
$W = [int]$bmp.Width; $H = [int]$bmp.Height
# jade footprint: G channel clearly above R/B (rgba(113,207,173,.55) on dark bg ~ RGB(69,123,106))
$jadeCols = [int[]]::new($W)
$rowHits = [int[]]::new($H)
for ($y = $Y0; $y -le $Y1; $y++) {
  for ($x = $X0; $x -le $X1; $x++) {
    $c = $bmp.GetPixel($x, $y)
    if ($c.G -ge 95 -and $c.G - $c.R -ge 25 -and $c.G - $c.B -ge 12) {
      $rowHits[$y]++
      $jadeCols[$x]++
    }
  }
}
"jade row bands (y,hits) in x${X0}-${X1}:"
$start = -1
for ($y = 0; $y -lt $H; $y++) {
  if ($rowHits[$y] -gt 3) {
    if ($start -lt 0) { $start = $y }
  } else {
    if ($start -ge 0) { "  band $start-$($y-1) len $($y-$start)" }
    $start = -1
  }
}
if ($start -ge 0) { "  band $start-$($H-1) len $($H-$start)" }
"jade column extent (min..max where col hits > 2):"
$c0 = -1; $c1 = -1
for ($x = 0; $x -lt $W; $x++) {
  if ($jadeCols[$x] -gt 2) { if ($c0 -lt 0) { $c0 = $x }; $c1 = $x }
}
"  x ${c0}..${c1}"
$bmp.Dispose()
