# Rebuilds and reloads the graph from the current raw data: normalize ->
# build graph elements -> build adjacency -> build proximity -> prune stale
# Neo4j nodes -> load.
# Run from the backend/ directory (or anywhere -- it cd's there itself).

$ErrorActionPreference = "Stop"
Set-Location -Path (Join-Path $PSScriptRoot "..")

$python = ".venv/Scripts/python.exe"

Write-Host "--- 1/6 normalize_places.py ---"
& $python scripts/normalize_places.py

Write-Host "`n--- 2/6 build_graph_elements.py ---"
& $python scripts/build_graph_elements.py

Write-Host "`n--- 3/6 build_adjacency.py ---"
& $python scripts/build_adjacency.py

Write-Host "`n--- 4/6 build_proximity.py ---"
& $python scripts/build_proximity.py

Write-Host "`n--- 5/6 prune_stale_places.py ---"
& $python scripts/prune_stale_places.py

Write-Host "`n--- 6/6 load_graph.py ---"
& $python scripts/load_graph.py

Write-Host "`nDone."