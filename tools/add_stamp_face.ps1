$ErrorActionPreference = 'Stop'

$dxfPath = 'D:\ai-novel-video-generator\assets\stamp\oval_stamp_face_mirrored.dxf'
$partPath = 'D:\ai-novel-video-generator\oval_stamp_head.SLDPRT'

$sw = [Runtime.InteropServices.Marshal]::GetActiveObject('SldWorks.Application.30')
$openErrors = 0
$openWarnings = 0
$model = $sw.OpenDoc6($partPath, 1, 1, '', [ref]$openErrors, [ref]$openWarnings)
if ($null -eq $model) {
    throw "Could not open part through the SolidWorks API (errors=$openErrors warnings=$openWarnings)"
}

$model.ClearSelection2($true)
$planes = New-Object System.Collections.Generic.List[object]
$walk = $model.FirstFeature()
while ($null -ne $walk) {
    if ($walk.GetTypeName2() -eq 'RefPlane') { $planes.Add($walk) }
    $walk = $walk.GetNextFeature()
}
if ($planes.Count -lt 2) {
    throw 'Could not find the standard reference planes'
}
$selected = $planes[1].Select2($false, 0)

$sketch = $model.SketchManager
$sketch.InsertSketch($true)
$sketch.AddToDB = $true
$sketch.DisplayWhenAdded = $false

$lines = Get-Content -LiteralPath $dxfPath
$contours = New-Object System.Collections.Generic.List[object]
$current = $null
$i = 0
while ($i -lt $lines.Count) {
    $code = $lines[$i].Trim()
    $value = if ($i + 1 -lt $lines.Count) { $lines[$i + 1].Trim() } else { '' }
    if ($code -eq '0' -and $value -eq 'LWPOLYLINE') {
        if ($null -ne $current -and $current.Count -ge 3) { $contours.Add($current) }
        $current = New-Object System.Collections.Generic.List[object]
        $i += 2
        continue
    }
    if ($null -ne $current -and $code -eq '10') {
        $x = [double]::Parse($value, [Globalization.CultureInfo]::InvariantCulture) / 1000.0
        if ($i + 3 -lt $lines.Count -and $lines[$i + 2].Trim() -eq '20') {
            $y = [double]::Parse($lines[$i + 3].Trim(), [Globalization.CultureInfo]::InvariantCulture) / 1000.0
            $current.Add(@($x, $y))
            $i += 4
            continue
        }
    }
    if ($null -ne $current -and $code -eq '0' -and $value -ne 'LWPOLYLINE') {
        if ($current.Count -ge 3) { $contours.Add($current) }
        $current = $null
    }
    $i += 2
}
if ($null -ne $current -and $current.Count -ge 3) { $contours.Add($current) }

$segmentCount = 0
foreach ($contour in $contours) {
    for ($j = 0; $j -lt $contour.Count; $j++) {
        $a = $contour[$j]
        $b = $contour[($j + 1) % $contour.Count]
        $null = $sketch.CreateLine($a[0], $a[1], 0.0, $b[0], $b[1], 0.0)
        $segmentCount++
    }
}

$sketch.DisplayWhenAdded = $true
$sketch.AddToDB = $false
$sketch.InsertSketch($true)

$feature = $model.FeatureManager.FeatureExtrusion2(
    $true, $false, $false,
    0, 0,
    0.006, 0.01,
    $false, $false, $false, $false,
    0.0, 0.0,
    $false, $false, $false, $false,
    $true, $true, $true,
    0, 0.0, $false
)
if ($null -eq $feature) {
    throw 'SolidWorks could not create the raised face extrusion'
}
$feature.Name = 'Raised_Mirrored_Stamp_Face'

$rebuild = $model.ForceRebuild3($false)
$saveErrors = 0
$saveWarnings = 0
$saved = $model.Extension.SaveAs($partPath, 0, 1, $null, [ref]$saveErrors, [ref]$saveWarnings)
if (-not $saved) {
    throw "Save failed (errors=$saveErrors warnings=$saveWarnings)"
}

Write-Output "Created $($contours.Count) contours with $segmentCount segments; rebuild=$rebuild; saveWarnings=$saveWarnings"
