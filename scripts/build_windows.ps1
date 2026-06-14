$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir
if (-not $env:SECOND_BRAIN_PROFILE) {
    $env:SECOND_BRAIN_PROFILE = "public"
}

if ($env:SECOND_BRAIN_RELEASE -eq "1") {
    $env:PYTHONPATH = "src"
    python scripts/validate_public_release.py
    if ($LASTEXITCODE -ne 0) { throw "Public release validation failed." }
}

python -m pip install -e ".[build]"
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
python -m PyInstaller --noconfirm --clean packaging/second_brain.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$AppExecutable = Join-Path $RootDir "dist\Second Brain Archive\Second Brain Archive.exe"
if (-not (Test-Path $AppExecutable)) {
    throw "Windows app bundle was not created: $AppExecutable"
}

function Find-SignTool {
    $Command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    $Candidates = Get-ChildItem `
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" `
        -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if ($Candidates) {
        return $Candidates[0].FullName
    }
    return $null
}

$CertificatePath = $null
$SignToolPath = $null
try {
    if ($env:WINDOWS_CERTIFICATE_BASE64) {
        $CertificatePath = Join-Path $env:TEMP "second-brain-certificate.pfx"
        [IO.File]::WriteAllBytes(
            $CertificatePath,
            [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE_BASE64)
        )
        $SignToolPath = Find-SignTool
        if (-not $SignToolPath) {
            throw "signtool.exe was not found."
        }
        & $SignToolPath sign `
            /f $CertificatePath `
            /p $env:WINDOWS_CERTIFICATE_PASSWORD `
            /fd SHA256 `
            /tr "http://timestamp.digicert.com" `
            /td SHA256 `
            $AppExecutable
        if ($LASTEXITCODE -ne 0) { throw "Application code signing failed." }
    }

    $Iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($Iscc) {
        $IsccPath = $Iscc.Source
    } else {
        $IsccPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    }
    if (-not (Test-Path $IsccPath)) {
        throw "Inno Setup 6 is required to create the Windows installer."
    }

    & $IsccPath "packaging\windows\SecondBrainArchive.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }
    $InstallerPath = Join-Path $RootDir "dist\installer\Second-Brain-Archive-Windows-x64.exe"
    if ($CertificatePath) {
        & $SignToolPath sign `
            /f $CertificatePath `
            /p $env:WINDOWS_CERTIFICATE_PASSWORD `
            /fd SHA256 `
            /tr "http://timestamp.digicert.com" `
            /td SHA256 `
            $InstallerPath
        if ($LASTEXITCODE -ne 0) { throw "Installer code signing failed." }
    }
    Write-Output $InstallerPath
} finally {
    if ($CertificatePath -and (Test-Path $CertificatePath)) {
        Remove-Item $CertificatePath -Force
    }
}
