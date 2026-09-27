param([string]$Src,[string]$Dst,[int]$X,[int]$Y,[int]$W,[int]$H)
Add-Type -AssemblyName System.Drawing
$src=[System.Drawing.Image]::FromFile($Src)
$bmp=New-Object System.Drawing.Bitmap $W,$H
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.DrawImage($src,(New-Object System.Drawing.Rectangle 0,0,$W,$H),(New-Object System.Drawing.Rectangle $X,$Y,$W,$H),[System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose();$bmp.Save($Dst,[System.Drawing.Imaging.ImageFormat]::Png);$bmp.Dispose();$src.Dispose()
"OK $Dst"
