# TLGL 沙箱操作备忘（本机真实约束）

## Bash 工具不可用
`dirname` / `head` / `grep` / `ls` / `cd` 全部 `command not found`（shim 依赖的
`shell-runtime-bash-env.sh` 自身就调 `dirname`，递归失败）。**一切命令走 PowerShell。**

## PowerShell 的两个坑
1. **吞 stdout**：前台 `& exe` 的输出经常拿不到。改成 `run_in_background: true`，
   或让脚本把结果写文件再 `Read`。
2. **编码**：
   - `> file` / `Out-File` 默认可能产出 UTF-16LE → Read 当二进制拒读。
     一律 `| Out-File X -Encoding UTF8` 或用 `*>`。
   - Rust 程序经 PowerShell 管道输出会被写成**双重编码**（UTF-8 字节被当 GBK 再编一次），
     Read 出来全是乱码。
     **正解：用托管 Python 的 `subprocess.run(capture_output=True)` 直接抓，
     再用 `p.stdout.decode('utf-8')` 写文件。** 不要经 PowerShell 中转中文输出。

## Rust 构建
- `$env:CARGO_TARGET_DIR = "D:\TLGL\.scratch\rc3"` + `--jobs 1`（并发构建会互踩）。
- PowerShell 会把 cargo 的进度行标成 `NativeCommandError`，**是假警报**，
  只认 `$LASTEXITCODE` 和末尾的 `error[` / `warning:`。
- 本项目 crates/core **没有** anyhow / image 依赖，新增 bin 别乱 use；
  快速加依赖会触发 `Locking N packages`，离线模式下可能失败。

## resources.db 口径
- 只读打开：`OpenFlags::SQLITE_OPEN_READ_ONLY | SQLITE_OPEN_NO_MUTEX`。
- `agroups` 主键是 `id`（**不是 gid**）。
- 无名贴图条件：`type='texture' AND (path IS NULL OR path='')`。
- 贴图合计 26,520：有名 2,259（全在 `ui/`）、无名 24,261。
