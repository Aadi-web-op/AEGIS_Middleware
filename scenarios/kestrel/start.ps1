# Kestrel dry run: start Neo4j, the AEGIS API and the console, load the
# company knowledge base, and (first run only) replay three weeks of traffic.
#
#   pwsh -File scenarios\kestrel\start.ps1 [-GroqKey gsk_...] [-Fresh]
#
# -GroqKey  enables "Generate & evaluate" (live RAG answers). Optional.
# -Fresh    wipes the dry-run graph, users and SQLite state and starts over.
#
# Secrets live in scenarios\kestrel\.env.local (gitignored), e.g.
#   AEGIS_ADMIN_EMAIL=you@example.com
#   AEGIS_ADMIN_PASSWORD=...           (10+ chars, upper, lower, digit, symbol)
# A random API key and Neo4j password are added on first run. They are loaded
# into this process's environment and inherited by the server windows, so no
# secret ever appears on a command line.
#
# Uses a separate Neo4j container (kestrel-neo4j), bound to localhost only, so
# the team's dev graph in aegis-neo4j is untouched; stop.ps1 switches back.
param([string]$GroqKey = $env:GROQ_API_KEY, [switch]$Fresh)
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Root = (Resolve-Path "$Here\..\..").Path
$Api = "http://localhost:8001"   # same site as the console, so the session cookie flows
$State = "$Here\.state"
$Secrets = "$Here\.env.local"
New-Item -ItemType Directory -Force $State | Out-Null

function Wait-Until($what, [scriptblock]$test, $seconds = 180) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) { try { if (& $test) { return } } catch {}; Start-Sleep 3 }
    throw "Timed out waiting for $what"
}
function New-Secret { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ }) }

# ------------------------------------------------------------------ secrets
if (-not (Test-Path $Secrets)) { throw "Create $Secrets with AEGIS_ADMIN_EMAIL and AEGIS_ADMIN_PASSWORD first." }
$vars = @{}
Get-Content $Secrets | Where-Object { $_ -match '^\s*([A-Z0-9_]+)=(.*)$' } | ForEach-Object { $vars[$matches[1]] = $matches[2] }
foreach ($name in "AEGIS_API_KEYS", "NEO4J_PASSWORD") {
    if (-not $vars[$name]) {
        $vars[$name] = if ($name -eq "AEGIS_API_KEYS") { "aegis_sk_" + (New-Secret) } else { New-Secret }
        Add-Content $Secrets "$name=$($vars[$name])"
    }
}
foreach ($k in $vars.Keys) { Set-Item "env:$k" $vars[$k] }
$env:NEO4J_URI = "bolt://localhost:7687"; $env:NEO4J_USER = "neo4j"
$env:USE_TF = "0"; $env:TRANSFORMERS_NO_TF = "1"
$env:AEGIS_CORS_ORIGINS = "http://localhost:8080,http://localhost:5173"
$env:AEGIS_AUDIT_DB_PATH = "$State\audit.db"
$env:AEGIS_ESCALATIONS_DB_PATH = "$State\escalations.db"
$env:AEGIS_USERS_DB_PATH = "$State\users.db"
$env:AEGIS_FACTS_DB_PATH = "$State\facts.db"
$env:AEGIS_AUTH_ENABLED = "1"
if ($GroqKey) { $env:GROQ_API_KEY = $GroqKey }
$env:VITE_AEGIS_API = $Api
$ServiceKey = ($env:AEGIS_API_KEYS -split ",")[0]

Write-Host "1/6 Docker and Neo4j" -ForegroundColor Cyan
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Wait-Until "Docker" { docker info *> $null; $LASTEXITCODE -eq 0 }
}
docker stop aegis-neo4j *> $null   # free ports 7474/7687; its data volume is kept
if ($Fresh) {
    docker rm -f kestrel-neo4j *> $null
    Remove-Item -Force -ErrorAction SilentlyContinue "$State\*.db"
}
docker inspect kestrel-neo4j *> $null
if ($LASTEXITCODE -ne 0) {
    # NEO4J_AUTH is read from this process's environment, not the command line.
    $env:NEO4J_AUTH = "neo4j/$($env:NEO4J_PASSWORD)"
    docker run -d --name kestrel-neo4j -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 `
        -e NEO4J_AUTH `
        -e NEO4J_server_memory_heap_initial__size=256m `
        -e NEO4J_server_memory_heap_max__size=512m `
        -e NEO4J_server_memory_pagecache_size=128m `
        neo4j:5.26-community | Out-Null
    Remove-Item env:NEO4J_AUTH
} else { docker start kestrel-neo4j | Out-Null }
Wait-Until "Neo4j" { (Invoke-WebRequest http://localhost:7474 -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }

Write-Host "2/6 AEGIS API on $Api (new window)" -ForegroundColor Cyan
$apiCmd = "`$Host.UI.RawUI.WindowTitle = 'AEGIS API :8001'; Set-Location '$Root'; python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-server-header"
if (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) { Write-Host "   already running" }
else { Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd }
Wait-Until "API health" { (Invoke-RestMethod "$Api/v1/health" -TimeoutSec 3).status -eq "ok" } 300
$auth = @{ "X-API-Key" = $ServiceKey }

Write-Host "3/6 Loading the Kestrel knowledge base (12 documents)" -ForegroundColor Cyan
$docs = python -c "import sys,json; sys.path.insert(0,r'$Here'); from corpus import DOCS; print(json.dumps([d for d in DOCS if d['preload']]))" | ConvertFrom-Json
foreach ($d in $docs) {
    $body = @{ pdf_path = "$Here\docs\$($d.file)"; source = $d.source; version = $d.version; date = $d.date } | ConvertTo-Json
    $r = Invoke-RestMethod "$Api/v1/rag/ingest" -Method Post -ContentType "application/json" -Body $body -Headers $auth -TimeoutSec 300
    Write-Host ("   {0,-48} v{1,-12} {2} chunk(s)" -f $d.file, $d.version, $r.chunks_added)
}

Write-Host "4/6 Traffic history" -ForegroundColor Cyan
$decisions = python -c @"
from neo4j import GraphDatabase; import os
d = GraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD']))
print(d.execute_query('MATCH (n:Decision) RETURN count(n) AS c').records[0]['c'])
"@
if ([int]$decisions -eq 0) {
    Set-Location $Root
    python "$Here\traffic.py" --api $Api
} else { Write-Host "   $decisions decisions already recorded; skipping replay (use -Fresh to start over)" }
Write-Host "   Fact Lock: locking Kestrel's key facts"
python "$Here\facts.py" --api $Api

Write-Host "5/6 Trust Console on http://localhost:8080 (new window)" -ForegroundColor Cyan
$feCmd = "`$Host.UI.RawUI.WindowTitle = 'AEGIS Console :8080'; Set-Location '$Root\frontend'; npm run dev"
if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue) { Write-Host "   already running" }
else { Start-Process powershell -ArgumentList "-NoExit", "-Command", $feCmd }
Wait-Until "console" { (Invoke-WebRequest http://localhost:8080 -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } 120

Write-Host "6/6 Ready" -ForegroundColor Green
Write-Host "   Console      http://localhost:8080   (sign in as $($env:AEGIS_ADMIN_EMAIL))"
Write-Host "   API docs     $Api/docs"
Write-Host "   Neo4j        http://localhost:7474   (user neo4j, password in .env.local)"
Write-Host "   Live RAG     $(if ($GroqKey) {'enabled'} else {'disabled - pass -GroqKey to enable Generate & evaluate'})"
Write-Host "   Security     python scripts\security_check.py"
Write-Host "   Walkthrough  scenarios\kestrel\EVALUATOR_GUIDE.md"
