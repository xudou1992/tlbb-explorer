param(
  [string]$Img,
  [int]$X0, [int]$Y0, [int]$W, [int]$H,
  [string]$Out
)
Add-Type -AssemblyName System.Drawing
$src = New-Object System.Drawing.Bitmap $Img
$bmp = New-Object System.Drawing.Bitmap $W, $H
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.DrawImage($src, (New-Object System.Drawing.Rectangle(0, 0, $W, $H)), (New-Object System.Drawing.Rectangle($X0, $Y0, $W, $H)), [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose(); $src.Dispose()
"CROP ${X0},${Y0} ${W}x${H} -> $Out"
