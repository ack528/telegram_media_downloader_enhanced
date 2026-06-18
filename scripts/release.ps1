param(
    [Parameter(Mandatory = $true)]
    [string]$CommitMessage,

    [Parameter(Mandatory = $true)]
    [string]$Tag,

    [string]$CommitBody = "",
    [string]$ReleaseName = "",
    [string]$ReleaseBody = "",
    [string]$Repo = "ack528/telegram_media_downloader_enhanced",
    [string]$Remote = "enhanced",
    [string]$Branch = "master",
    [string]$SpecPath = "media_downloader.spec",
    [string]$AssetPath = "dist\tdl.exe",
    [switch]$SkipTests,
    [switch]$NoBuild,
    [switch]$Prerelease,
    [switch]$Draft
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    Write-Host ">> $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Get-GitHubToken {
    $credentialInput = "protocol=https`nhost=github.com`n`n"
    $credentialText = $credentialInput | git credential fill
    $token = ($credentialText -split "`n" |
        Where-Object { $_ -like "password=*" } |
        Select-Object -First 1) -replace "^password=", ""

    if (-not $token) {
        throw "Could not read GitHub token from Git Credential Manager. Please sign in with Git first."
    }

    return $token
}

function Copy-BuildAsset {
    param([string]$OutputPath)

    $exePath = "dist\tdl.exe"
    if (-not (Test-Path $exePath)) {
        throw "Build output not found: $exePath"
    }

    $outputDir = Split-Path $OutputPath -Parent
    if ($outputDir -and -not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir | Out-Null
    }

    $sourcePath = (Resolve-Path $exePath).Path
    $targetPath = [IO.Path]::GetFullPath($OutputPath)

    if ((Test-Path $OutputPath) -and ($targetPath -ne $sourcePath)) {
        Remove-Item -LiteralPath $OutputPath -Force
    }

    if ($targetPath -ne $sourcePath) {
        Copy-Item -LiteralPath $exePath -Destination $OutputPath -Force
    }

    Write-Host "Created asset: $OutputPath"
}

function Invoke-GitCommitIfNeeded {
    param(
        [string]$Message,
        [string]$Body
    )

    Invoke-Checked git @("add", "-A")

    $staged = git diff --cached --name-only
    if (-not $staged) {
        Write-Host "No staged changes. Skipping commit."
        return
    }

    if ($Body) {
        Invoke-Checked git @("commit", "-m", $Message, "-m", $Body)
    } else {
        Invoke-Checked git @("commit", "-m", $Message)
    }
}

function Assert-TagAvailable {
    param(
        [string]$RemoteName,
        [string]$TagName
    )

    $localTag = git tag --list $TagName
    if ($localTag) {
        throw "Local tag already exists: $TagName"
    }

    $remoteTag = git ls-remote --tags $RemoteName $TagName
    if ($remoteTag) {
        throw "Remote tag already exists: $TagName"
    }
}

function Publish-GitHubRelease {
    param(
        [string]$Repository,
        [string]$TagName,
        [string]$Name,
        [string]$Body,
        [string]$Asset,
        [bool]$IsPrerelease,
        [bool]$IsDraft
    )

    if (-not (Test-Path $Asset)) {
        throw "Release asset not found: $Asset"
    }

    if (-not $Name) {
        $Name = $TagName
    }

    if (-not $Body) {
        $Body = "Automated release for $TagName.`n`nAsset:`n- $(Split-Path $Asset -Leaf)"
    }

    $token = Get-GitHubToken
    $headers = @{
        Authorization = "Bearer $token"
        Accept = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    try {
        $release = Invoke-RestMethod `
            -Method Get `
            -Uri "https://api.github.com/repos/$Repository/releases/tags/$TagName" `
            -Headers $headers
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) {
            throw
        }

        $createBody = @{
            tag_name = $TagName
            target_commitish = $Branch
            name = $Name
            body = $Body
            draft = $IsDraft
            prerelease = $IsPrerelease
        } | ConvertTo-Json

        $release = Invoke-RestMethod `
            -Method Post `
            -Uri "https://api.github.com/repos/$Repository/releases" `
            -Headers $headers `
            -Body $createBody `
            -ContentType "application/json"
    }

    $assetName = Split-Path $Asset -Leaf
    foreach ($existingAsset in $release.assets) {
        if ($existingAsset.name -eq $assetName) {
            Invoke-RestMethod `
                -Method Delete `
                -Uri "https://api.github.com/repos/$Repository/releases/assets/$($existingAsset.id)" `
                -Headers $headers | Out-Null
        }
    }

    $escapedAssetName = [uri]::EscapeDataString($assetName)
    $uploadUrl = $release.upload_url -replace "\{\?name,label\}", "?name=$escapedAssetName"
    $contentType = "application/octet-stream"
    if ([IO.Path]::GetExtension($Asset).ToLowerInvariant() -eq ".zip") {
        $contentType = "application/zip"
    }

    Invoke-RestMethod `
        -Method Post `
        -Uri $uploadUrl `
        -Headers $headers `
        -InFile (Resolve-Path $Asset).Path `
        -ContentType $contentType | Out-Null

    Write-Host "Release published: $($release.html_url)"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

if (-not $ReleaseName) {
    $ReleaseName = $Tag
}

Assert-TagAvailable -RemoteName $Remote -TagName $Tag

if (-not $SkipTests) {
    Invoke-Checked ".\.venv\Scripts\python.exe" @(
        "-m",
        "unittest",
        "tests.module.test_bot_status",
        "tests.module.test_clash_controller",
        "tests.module.test_app_recovery",
        "tests.utils.test_format"
    )
    Invoke-Checked ".\.venv\Scripts\python.exe" @(
        "-m",
        "py_compile",
        "media_downloader.py",
        "module\app.py",
        "module\download_stat.py",
        "module\pyrogram_extension.py",
        "module\clash_controller.py",
        "module\network_watchdog.py"
    )
}

if (-not $NoBuild) {
    Invoke-Checked ".\.venv\Scripts\python.exe" @(
        "-m",
        "PyInstaller",
        $SpecPath,
        "--clean",
        "--noconfirm"
    )
    Copy-BuildAsset -OutputPath $AssetPath
}

Invoke-GitCommitIfNeeded -Message $CommitMessage -Body $CommitBody

Invoke-Checked git @("push", $Remote, $Branch)
Invoke-Checked git @("tag", "-a", $Tag, "-m", "Release $Tag")
Invoke-Checked git @("push", $Remote, $Tag)

Publish-GitHubRelease `
    -Repository $Repo `
    -TagName $Tag `
    -Name $ReleaseName `
    -Body $ReleaseBody `
    -Asset $AssetPath `
    -IsPrerelease ([bool]$Prerelease) `
    -IsDraft ([bool]$Draft)

Write-Host "Done."
