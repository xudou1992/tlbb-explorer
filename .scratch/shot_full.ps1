Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$b=[System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X,$b.Y,0,0,$b.Size)
$bmp.Save("D:\TLGL\.scratch\screen_full.png",[System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose();$bmp.Dispose()
"OK $($b.Width)x$($b.Height)" | Out-File -Encoding ascii D:\TLGL\.scratch\screen_full_status.txt
