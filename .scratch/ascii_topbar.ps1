param(
  [string]$Img = "D:/TLGL/.scratch/topbar_crop.png",
  [int]$X0 = 470,
  [int]$X1 = 659,
  [int]$Y0 = 35,
  [int]$Y1 = 100,
  [int]$Thresh = 90
)
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap $Img
"crop-region x${X0}-${X1} y${Y0}-${Y1} thresh=$Thresh (each col = 2px, each row = 1px)"
$xscale = 2
for ($y = $Y0; $y -le $Y1; $y++) {
  $line = ""
  for ($xx = $X0; $xx -le $X1; $xx += $xscale) {
    $any = $false
    for ($k = 0; $k -lt $xscale -and ($xx + $k) -le $X1; $k++) {
      $c = $bmp.GetPixel($xx + $k, $y)
      if ([int](($c.R + $c.G + $c.B) / 3) -ge $Thresh) { $any = $true; break }
    }
    $line += $(if ($any) { "#" } else { "." })
  }
  "{0,3} {1}" -f $y, $line
}
$bmp.Dispose()
