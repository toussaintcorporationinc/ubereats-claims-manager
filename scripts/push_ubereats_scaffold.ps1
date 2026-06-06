$ErrorActionPreference = "Stop"

Write-Host "=== Uber Eats Claims Manager - push autopilote ===" -ForegroundColor Cyan

$DefaultRepoUrl = "https://github.com/toussaintcorporationinc/ubereats-claims-manager.git"
$RepoUrl = if ($env:UBEREATS_CLAIMS_REPO_URL) { $env:UBEREATS_CLAIMS_REPO_URL } else { $DefaultRepoUrl }
$TargetDir = if ($env:UBEREATS_CLAIMS_TARGET_DIR) {
    $env:UBEREATS_CLAIMS_TARGET_DIR
} else {
    Join-Path $env:USERPROFILE "Documents\ubereats-claims-manager-clean"
}

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Fail($Message) {
    Write-Host "ERREUR: $Message" -ForegroundColor Red
    Write-Host ""
    Read-Host "Appuie sur Entree pour fermer"
    exit 1
}

function Run-Git([string[]]$ArgsList, [string]$WorkingDir = $null) {
    if ($WorkingDir) { Push-Location $WorkingDir }
    try {
        & git @ArgsList
        if ($LASTEXITCODE -ne 0) {
            throw "git $($ArgsList -join ' ') a echoue avec code $LASTEXITCODE"
        }
    }
    finally {
        if ($WorkingDir) { Pop-Location }
    }
}

function Assert-ProjectSource($SourceDir) {
    $requiredFiles = @(
        "backend\app\main.py",
        "frontend\app\page.tsx",
        "docker-compose.yml",
        "README.md"
    )

    foreach ($relativePath in $requiredFiles) {
        $fullPath = Join-Path $SourceDir $relativePath
        if (-not (Test-Path -LiteralPath $fullPath)) {
            Fail "Source invalide: fichier manquant $relativePath"
        }
    }
}

try {
    & git --version | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Git introuvable" }
} catch {
    Fail "Git n'est pas installe ou pas reconnu. Installe Git for Windows puis relance ce script."
}

Assert-ProjectSource $ProjectRoot
Write-Host "Source projet: $ProjectRoot" -ForegroundColor Green

if (-not (Test-Path -LiteralPath $TargetDir)) {
    Write-Host "Clonage du vrai repo GitHub..." -ForegroundColor Cyan
    Run-Git -ArgsList @("clone", $RepoUrl, $TargetDir)
} else {
    Write-Host "Dossier cible deja present: $TargetDir" -ForegroundColor Yellow
    if (-not (Test-Path -LiteralPath (Join-Path $TargetDir ".git"))) {
        Fail "Le dossier cible existe mais n'est pas un repo Git: $TargetDir"
    }
}

Push-Location $TargetDir
try {
    $RemoteUrl = (& git remote get-url origin) 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "Aucun remote origin dans $TargetDir" }
    if ($RemoteUrl -notlike "*ubereats-claims-manager*") {
        Fail "Remote inattendu: $RemoteUrl"
    }

    Write-Host "Mise a jour de main..." -ForegroundColor Cyan
    Run-Git -ArgsList @("fetch", "origin")
    Run-Git -ArgsList @("checkout", "main")
    Run-Git -ArgsList @("pull", "--ff-only", "origin", "main")

    if (-not (Test-Path -LiteralPath (Join-Path $TargetDir "AGENTS.md"))) {
        Write-Host "Attention: AGENTS.md absent dans le repo cible." -ForegroundColor Yellow
    }

    $BranchName = "v1-scaffold-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    Write-Host "Creation branche: $BranchName" -ForegroundColor Cyan
    Run-Git -ArgsList @("checkout", "-b", $BranchName)

    Write-Host "Copie des fichiers projet vers le repo cible..." -ForegroundColor Cyan
    $robocopyArgs = @(
        $ProjectRoot,
        $TargetDir,
        "/E",
        "/XD", ".git", "work", ".venv", "venv", "node_modules", "__pycache__", ".next", "dist", "build", ".pytest_cache", ".ruff_cache",
        "/XF", ".env", ".env.*", "*.pyc", "*.tsbuildinfo"
    )
    & robocopy @robocopyArgs | Out-Host
    $robocopyCode = $LASTEXITCODE
    if ($robocopyCode -gt 7) {
        Fail "Robocopy a echoue avec code $robocopyCode"
    }

    $envExample = Join-Path $ProjectRoot ".env.example"
    if (Test-Path -LiteralPath $envExample) {
        Copy-Item -LiteralPath $envExample -Destination (Join-Path $TargetDir ".env.example") -Force
    }

    Write-Host "Fichiers modifies:" -ForegroundColor Cyan
    & git status --short | Out-Host

    $status = (& git status --porcelain)
    if (-not $status) {
        Write-Host "Aucun changement a commit." -ForegroundColor Yellow
    } else {
        $userName = (& git config user.name) 2>$null
        if (-not $userName) { & git config user.name "Toussaint Codex" }
        $userEmail = (& git config user.email) 2>$null
        if (-not $userEmail) { & git config user.email "codex-local@users.noreply.github.com" }

        Run-Git -ArgsList @("add", ".")
        Run-Git -ArgsList @("commit", "-m", "Initial project scaffold")
    }

    Write-Host "Push vers GitHub..." -ForegroundColor Cyan
    Run-Git -ArgsList @("push", "-u", "origin", $BranchName)

    Write-Host ""
    Write-Host "OK. Branche poussee: $BranchName" -ForegroundColor Green
    Write-Host "Ouvre cette URL pour creer la PR:" -ForegroundColor Green
    Write-Host "https://github.com/toussaintcorporationinc/ubereats-claims-manager/compare/main...$BranchName?expand=1" -ForegroundColor Cyan
}
finally {
    Pop-Location
}

Write-Host ""
Read-Host "Termine. Appuie sur Entree pour fermer"
