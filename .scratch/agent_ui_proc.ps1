$ErrorActionPreference = 'SilentlyContinue'
"=== tlbb-shell processes ==="
Get-CimInstance Win32_Process -Filter "Name='tlbb-shell.exe'" |
  ForEach-Object {
    "PID=$($_.ProcessId)"
    "  Created=$($_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss'))"
    "  Path=$($_.ExecutablePath)"
    "  Cmd=$($_.CommandLine)"
    "  Parent=$($_.ParentProcessId)"
  }
"=== all processes with tlbb in name ==="
Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*tlbb*' } |
  ForEach-Object { "PID=$($_.ProcessId) Name=$($_.Name) Created=$($_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss')) Path=$($_.ExecutablePath)" }
"=== exe files ==="
foreach ($p in @(
  'D:\TLGL\tlbb-explorer\app\src-tauri\target\debug\tlbb-shell.exe',
  'D:\TLGL\.scratch\rc3\debug\tlbb-shell.exe',
  'D:\TLGL\tlbb-explorer\app\src-tauri\target\release\tlbb-shell.exe'
)) {
  $i = Get-Item $p
  if ($i) { "MTIME=$($i.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))  SIZE=$($i.Length)  PATH=$($i.FullName)" }
  else { "MISSING  $p" }
}
"=== web sources + dist ==="
foreach ($d in @('D:\TLGL\tlbb-explorer\app\web', 'D:\TLGL\tlbb-explorer\app\web\dist')) {
  Get-ChildItem $d -File | ForEach-Object { "MTIME=$($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))  SIZE=$($_.Length)  $($_.FullName)" }
}
"=== rust sources ==="
Get-ChildItem 'D:\TLGL\tlbb-explorer\app\src-tauri\src' -File | ForEach-Object { "MTIME=$($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))  SIZE=$($_.Length)  $($_.FullName)" }
"=== core crate sources (newest 12) ==="
Get-ChildItem 'D:\TLGL\tlbb-explorer\crates\core\src' -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 12 |
  ForEach-Object { "MTIME=$($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))  $($_.FullName)" }
"=== now ==="
"NOW=$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))"
