param(
  [string]$Img = "D:/TLGL/.scratch/topbar_crop.png",
  [int]$Thresh = 120,
  [int]$Y0 = 55,
  [int]$Y1 = 90
)
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap $Img
$w = $bmp.Width; $h = $bmp.Height
"IMG ${w}x${h} thresh=$Thresh rows ${Y0}-${Y1}"

# 只在指定行带内做列直方图
$colHits = New-Object int[] $w
for ($y = $Y0; $y -le $Y1; $y++) {
  if ($y -lt 0 -or $y -ge $h) { continue }
  for ($x = 0; $x -lt $w; $x++) {
    $c = $bmp.GetPixel($x, $y)
    $bri = [int](($c.R + $c.G + $c.B) / 3)
    if ($bri -ge $Thresh) { $colHits[$x]++ }
  }
}
"col runs (start,end,len,maxhits):"
$start = -1; $maxh = 0
for ($i = 0; $i -lt $w; $i++) {
  if ($colHits[$i] -gt 0) {
    if ($start -lt 0) { $start = $i; $maxh = $colHits[$i] }
    elseif ($colHits[$i] -gt $maxh) { $maxh = $colHits[$i] }
  } else {
    if ($start -ge 0) {
      "  {0},{1},{2},{3}" -f $start, ($i - 1), ($i - $start), $maxh
      $start = -1; $maxh = 0
    }
  }
}
if ($start -ge 0) { "  {0},{1},{2},{3}" -f $start, ($w - 1), ($w - $start), $maxh }

# 行带内的行直方图（确认按钮整体高度范围，含边框的话阈值要降）
$rowHits = New-Object int[] $h
for ($y = 0; $y -lt $h; $y++) {
  for ($x = 0; $x -lt $w; $x++) {
    $c = $bmp.GetPixel($x, $y)
    $bri = [int](($c.R + $c.G + $c.B) / 3)
    if ($bri -ge $Thresh) { $rowHits[$y]++ }
  }
}
"row histogram (y:hits):"
for ($y = 0; $y -lt $h; $y++) { if ($rowHits[$y] -gt 0) { "  {0}:{1}" -f $y, $rowHits[$y] } }
$bmp.Dispose()
