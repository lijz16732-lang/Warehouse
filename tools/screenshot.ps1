# 截取整个主屏并保存 PNG（无需 PIL）
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$g.Dispose()
$bmp.Save("OUT_PATH", [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output "saved"
