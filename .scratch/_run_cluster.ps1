$ErrorActionPreference = 'Continue'
$exe = "D:\TLGL\.scratch\rc3\debug\texture_cluster.exe"
if (-not (Test-Path $exe)) { "NO EXE: $exe" | Out-File D:\TLGL\.scratch\_run_cluster.txt -Encoding UTF8; exit 1 }
$sw = [System.Diagnostics.Stopwatch]::StartNew()
& $exe --root D:/TLGL --db D:/TLGL/.scratch/resources.db --sample 12 --json D:/TLGL/.scratch/cluster.json *> D:\TLGL\.scratch\_run_cluster.txt
$code = $LASTEXITCODE
$sw.Stop()
"EXIT=$code ELAPSED=$($sw.Elapsed.TotalSeconds)" | Out-File D:\TLGL\.scratch\_run_cluster_exit.txt -Encoding UTF8
