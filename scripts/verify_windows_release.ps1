param(
    [string]$Installer = ""
)

$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$verification = Join-Path $workspace 'build\verification'
$installDir = [IO.Path]::GetFullPath((Join-Path $verification 'installed-app'))
$registrySuffix = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{2C1D19CA-A9C6-42D9-A8B9-2EBB65852FE5}_is1'
$registryKey = "HKCU:\$registrySuffix"
$metadata = Get-Content -LiteralPath (Join-Path $workspace 'author_info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$shortcutDir = Join-Path ([Environment]::GetFolderPath('Programs')) $metadata.app_name
$userData = Join-Path $env:APPDATA 'AutoDeliver'
if (-not $Installer) {
    $Installer = Join-Path $workspace ("release\AutoDeliver-Setup-{0}-win64.exe" -f $metadata.version)
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
if (-not $installDir.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Test installation must stay inside the workspace: $installDir"
}
foreach ($key in @($registryKey, "HKLM:\$registrySuffix", "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{2C1D19CA-A9C6-42D9-A8B9-2EBB65852FE5}_is1")) {
    if (Test-Path -LiteralPath $key) { throw "An installation already exists: $key" }
}
if ((Test-Path -LiteralPath $installDir) -or (Test-Path -LiteralPath $shortcutDir)) {
    throw 'The test installation or shortcut directory already exists.'
}
New-Item -ItemType Directory -Path $verification -Force | Out-Null

function Get-UserDataSnapshot {
    if (-not (Test-Path -LiteralPath $userData)) { return @() }
    return @(Get-ChildItem -LiteralPath $userData -File -Recurse -Force |
        Where-Object { $_.Name -notlike '*.log' -and $_.Name -notlike '*.log.*' } |
        Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($userData.Length + 1)
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    })
}

function Invoke-CheckedProcess {
    param([string]$Executable, [string[]]$Arguments, [int]$TimeoutSeconds = 180)
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force
        throw "Timed out after ${TimeoutSeconds}s: $Executable"
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "Process exited with $($process.ExitCode): $Executable" }
}

$before = Get-UserDataSnapshot
$beforeJson = ConvertTo-Json -InputObject @($before) -Depth 4 -Compress
$result = [ordered]@{
    ok = $false
    installer = $Installer
    installer_sha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
    install_dir = $installDir
    install_ok = $false
    installed_self_check_ok = $false
    uninstall_ok = $false
    user_data_unchanged = $false
    user_data_excluded_patterns = @('*.log', '*.log.*')
}
$testInstallStarted = $false
try {
    $testInstallStarted = $true
    Invoke-CheckedProcess $Installer @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCLOSEAPPLICATIONS',
        ('/DIR="{0}"' -f $installDir),
        '/TASKS="!desktopicon"', ('/LOG="{0}"' -f (Join-Path $verification 'install.log'))
    )
    $registration = Get-ItemProperty -LiteralPath $registryKey
    $registeredDir = [IO.Path]::GetFullPath($registration.InstallLocation).TrimEnd('\')
    if ($registeredDir -ne $installDir) { throw "Unexpected registered install location: $registeredDir" }
    if ($registration.Publisher -ne 'Gnahz') { throw 'Installer author metadata is incorrect.' }
    if ($registration.DisplayVersion -ne $metadata.version) { throw 'Installed version does not match application metadata.' }
    if (-not (Test-Path -LiteralPath (Join-Path $shortcutDir ($metadata.app_name + '.lnk')))) {
        throw 'Start Menu shortcut was not created.'
    }
    $result.install_ok = $true
    $reportPath = Join-Path $verification 'installed-check.json'
    Invoke-CheckedProcess (Join-Path $installDir 'AutoDeliver.exe') @('--self-check', ('"{0}"' -f $reportPath)) 90
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $worker = Get-Content -LiteralPath (Join-Path $verification 'installed-check-worker.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not ($report.ok -and $report.frozen -and $report.about_ok -and $report.worker_ok -and $worker.ok)) {
        throw 'Installed application self-check failed.'
    }
    $result.installed_self_check_ok = $true
    $result.browser_launch_ok = $worker.browser_launch_ok
} catch {
    $result.error = $_.Exception.Message
} finally {
    try {
        $uninstaller = Join-Path $installDir 'unins000.exe'
        if ($testInstallStarted -and (Test-Path -LiteralPath $uninstaller)) {
            $resolvedInstall = (Resolve-Path -LiteralPath $installDir).Path
            $resolvedWorkspace = (Resolve-Path -LiteralPath $workspace).Path
            if (-not $resolvedInstall.StartsWith($resolvedWorkspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to uninstall outside the workspace: $resolvedInstall"
            }
            if ((Get-Item -LiteralPath $installDir).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Refusing to uninstall a reparse-point directory.'
            }
            Invoke-CheckedProcess $uninstaller @(
                '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                ('/LOG="{0}"' -f (Join-Path $verification 'uninstall.log'))
            )
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            while ((Test-Path -LiteralPath $uninstaller) -and [DateTime]::UtcNow -lt $deadline) {
                Start-Sleep -Milliseconds 200
            }
            if ((Test-Path -LiteralPath $installDir) -or (Test-Path -LiteralPath $registryKey) -or (Test-Path -LiteralPath $shortcutDir)) {
                throw 'Test installation files, registration, or shortcuts remain after uninstall.'
            }
            $result.uninstall_ok = $true
        }
        $after = Get-UserDataSnapshot
        $afterJson = ConvertTo-Json -InputObject @($after) -Depth 4 -Compress
        $result.user_data_unchanged = $beforeJson -eq $afterJson
        $result.user_data_file_count = @($before).Count
        if (-not $result.user_data_unchanged) {
            throw 'User data changed during verification; inspect active app activity before attributing the change.'
        }
    } catch {
        $result.cleanup_error = $_.Exception.Message
    }
    $result.ok = $result.install_ok -and $result.installed_self_check_ok -and $result.uninstall_ok -and $result.user_data_unchanged
    $result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $verification 'installer-check.json') -Encoding UTF8
}
$result | ConvertTo-Json -Depth 4
if (-not $result.ok) { exit 1 }
