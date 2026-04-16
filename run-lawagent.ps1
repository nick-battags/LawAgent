param(
    [string]$FallbackOllamaIp = "",
    [switch]$LocalOnly
)

$ErrorActionPreference = "Stop"

function Set-EnvDefault {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $current = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($current)) {
        Set-Item -Path "Env:$Name" -Value $Value
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Missing .venv python at .\.venv\Scripts\python.exe. Create your venv first."
}

$env:ADMIN_PIN = "1322"
$env:FLASK_SECRET_KEY = "R@mblerstags67."
Set-EnvDefault -Name "LAWAGENT_RUNTIME_MODE" -Value "auto"
Set-EnvDefault -Name "LAWAGENT_ALLOW_RUNTIME_MODE_OVERRIDE" -Value "true"
Set-EnvDefault -Name "GRADER_MODEL" -Value "llama3.1:8b"
Set-EnvDefault -Name "GENERATOR_MODEL" -Value "command-r:7b"
Set-EnvDefault -Name "EMBEDDING_MODEL" -Value "nomic-embed-text"
Set-EnvDefault -Name "OLLAMA_EMBED_TIMEOUT_SEC" -Value "180"
Set-EnvDefault -Name "VECTOR_UPSERT_BATCH_SIZE" -Value "64"
Set-EnvDefault -Name "VECTOR_UPSERT_MIN_BATCH_SIZE" -Value "8"

$primary = "http://127.0.0.1:11434"
if ($LocalOnly) {
    $env:OLLAMA_BASE_URLS = $primary
} elseif (-not [string]::IsNullOrWhiteSpace($FallbackOllamaIp)) {
    $fallback = "http://$FallbackOllamaIp`:11434"
    $env:OLLAMA_BASE_URLS = "$primary,$fallback"
} elseif ([string]::IsNullOrWhiteSpace($env:OLLAMA_BASE_URLS)) {
    $env:OLLAMA_BASE_URLS = $primary
}

Write-Host "LawAgent root: $repoRoot"
Write-Host "Runtime mode: $env:LAWAGENT_RUNTIME_MODE"
Write-Host "OLLAMA_BASE_URLS: $env:OLLAMA_BASE_URLS"

try {
    $null = Invoke-RestMethod "$primary/api/tags" -TimeoutSec 2
    Write-Host "Primary Ollama endpoint reachable."
} catch {
    Write-Warning "Primary Ollama endpoint not reachable at $primary. App can still start."
}

& ".\.venv\Scripts\python.exe" "app.py"
