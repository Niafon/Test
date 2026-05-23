$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Recreating source-postgres and target-postgres from scratch..."
docker compose -f "$projectRoot/docker-compose.yml" down -v --remove-orphans
if ($LASTEXITCODE -ne 0) {
    throw "docker compose down failed"
}

docker compose -f "$projectRoot/docker-compose.yml" up -d
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed"
}

Write-Host "Waiting for PostgreSQL containers to become healthy..."
docker compose -f "$projectRoot/docker-compose.yml" ps

Write-Host "Test environment has been reset."
