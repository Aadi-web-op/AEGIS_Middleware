# Stop the Kestrel dry run and switch back to the team's dev Neo4j.
#   pwsh -File scenarios\kestrel\stop.ps1
foreach ($port in 8001, 8080) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
docker stop kestrel-neo4j *> $null
docker start aegis-neo4j *> $null
Write-Host "Dry run stopped. Dry-run data is kept (kestrel-neo4j container, scenarios\kestrel\.state)."
Write-Host "aegis-neo4j (dev graph) is running again."
