param(
    [string]$Python = 'python',
    [string]$Iscc = '',
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location $root
try {
    $metadata = Get-Content -LiteralPath (Join-Path $root 'author_info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $version = $metadata.version
    if (-not $SkipTests) {
        $oldQtPlatform = $env:QT_QPA_PLATFORM
        $env:QT_QPA_PLATFORM = 'offscreen'
        try {
            & $Python -X utf8 -B -m pytest tests -q
            if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed.' }
        } finally { $env:QT_QPA_PLATFORM = $oldQtPlatform }
    }
    & $Python -X utf8 -B packaging/build_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    & $Python -X utf8 -B -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/AutoDeliver.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    $report = Join-Path $root 'build\verification\package-check.json'
    $check = Start-Process -FilePath (Join-Path $root 'dist\AutoDeliver\AutoDeliver.exe') -ArgumentList @('--self-check', ('"'+$report+'"')) -WindowStyle Hidden -PassThru
    if (-not $check.WaitForExit(90000)) {
        Stop-Process -Id $check.Id
        throw 'Package self-check timed out.'
    }
    $check.Refresh()
    if ($check.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw "Package self-check failed: $report" }
    if (-not (Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json).ok) { throw "Package self-check failed: $report" }
    if (-not $Iscc) {
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA 'AutoDeliverBuildTools\InnoSetup\ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
        )
        $Iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $Iscc) { throw 'Inno Setup compiler not found. Pass -Iscc with the ISCC.exe path.' }
    & $Iscc packaging/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    $setup = Join-Path $root ("release\AutoDeliver-Setup-{0}-win64.exe" -f $version)
    $zip = Join-Path $root ("release\AutoDeliver-{0}-win64-portable.zip" -f $version)
    Compress-Archive -LiteralPath (Join-Path $root 'dist\AutoDeliver') -DestinationPath $zip -Force
    Get-FileHash -LiteralPath $setup, $zip -Algorithm SHA256 | Format-Table -AutoSize
} finally { Pop-Location }
