param([string]$Img, [int]$X0 = 280, [int]$Y0 = 150, [int]$X1 = 1060, [int]$Y1 = 840)
Add-Type -AssemblyName System.Drawing
$bmp = [System.Drawing.Bitmap]::FromFile($Img)
$light = 0
$total = 0
$brightest = 0
$sample = ""
for ($y = $Y0; $y -lt $Y1; $y += 3) {
  for ($x = $X0; $x -lt $X1; $x += 3) {
    $c = $bmp.GetPixel($x, $y)
    $total++
    $lum = ($c.R + $c.G + $c.B) / 3
    if ($lum -gt $brightest) { $brightest = $lum; $sample = "$x,$y : $($c.R),$($c.G),$($c.B)" }
    if ($lum -gt 90) { $light++ }
  }
}
Write-Output ("region=$X0,$Y0..$X1,$Y1 sampled=$total light_px=$light brightest=$([int]$brightest) at $sample")
$bmp.Dispose()
