param([string]$ArchiveDir = '')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
if (-not $ArchiveDir) {
    $ArchiveDir = Join-Path (Split-Path $root -Parent) ('AutoDeliver-archive-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$archive = [IO.Path]::GetFullPath($ArchiveDir).TrimEnd('\')
if ($archive -eq $root -or $archive.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The archive must be outside the source tree.'
}
if (Test-Path -LiteralPath $archive) { throw 'Choose a new archive directory to preserve earlier archives.' }
New-Item -ItemType Directory -Path $archive | Out-Null
$names = @(
    '.env', '.screenshots', '.playwright-cli', '网页示例',
    'candidate_profile.json', 'job_profiles.json', 'nonexistent_job_profiles.json',
    'resume_digest.json', 'interview_draft_cache.json'
)
$targets = @(Get-ChildItem -LiteralPath $root -Force | Where-Object {
    $_.Name -in $names -or $_.Extension -in '.csv', '.bak'
})
$manifest = @()
foreach ($target in $targets) {
    $source = [IO.Path]::GetFullPath($target.FullName)
    $destination = [IO.Path]::GetFullPath((Join-Path $archive $target.Name))
    if (-not $source.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
        -not $destination.StartsWith($archive + '\', [StringComparison]::OrdinalIgnoreCase) -or
        ($target.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe archive target.' }
    $files = if ($target.PSIsContainer) { @(Get-ChildItem -LiteralPath $source -Recurse -File -Force) } else { @($target) }
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($root.Length + 1)
        $manifest += [pscustomobject]@{
            Path=$relative; Bytes=$file.Length; SHA256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        }
    }
    Move-Item -LiteralPath $source -Destination $destination
}
foreach ($entry in $manifest) {
    $copy = Join-Path $archive $entry.Path
    if ((Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash -ne $entry.SHA256) { throw "Archive verification failed: $($entry.Path)" }
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $archive 'manifest.json') -Encoding UTF8
foreach ($relative in @('__pycache__', '.pytest_cache', 'tests\__pycache__', 'scripts\__pycache__', 'scripts\startup_smoke_support\__pycache__')) {
    $cache = [IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $cache.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe cache target.' }
    if (Test-Path -LiteralPath $cache) {
        if ((Get-Item -LiteralPath $cache).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing to remove a linked cache.' }
        Remove-Item -LiteralPath $cache -Recurse -Force
    }
}
[pscustomobject]@{Archive=$archive; ArchivedItems=$targets.Count; VerifiedFiles=$manifest.Count}
