$exe = "D:\TLGL\.scratch\rc3\debug\texture_cluster.exe"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
& $exe --root "D:/TLGL" --db "D:/TLGL/.scratch/resources.db" --pool 3000 --per-cluster 40 --json "D:/TLGL/.scratch/cluster2.json" --sheet "D:/TLGL/.scratch/sheet" --thumb 64 *> D:\TLGL\.scratch\_tc2_run.txt
$code = $LASTEXITCODE
$sw.Stop()
"EXIT=$code ELAPSED=$($sw.Elapsed.TotalSeconds)" | Out-File D:\TLGL\.scratch\_tc2_run_exit.txt -Encoding UTF8
