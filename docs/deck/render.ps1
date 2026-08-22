$deck = "C:\Users\mohit\hackathons\unihack\caliper\docs\deck\CALIPER_UniHack.pptx"
$out  = "C:\Users\mohit\hackathons\unihack\caliper\docs\deck\render"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($deck, $true, $false, $false)
$pres.SaveAs($out, 18)
$pres.Close(); $app.Quit()
