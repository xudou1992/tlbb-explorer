#!/bin/bash
# 等并行会话把核心 crate 修好，期间反复尝试构建；成功即退出。
cd /d/TLGL/tlbb-explorer/app/src-tauri || exit 1
for i in $(seq 1 30); do
  if cargo build 2>/tmp/build.err; then
    echo "BUILD OK on attempt $i"
    exit 0
  fi
  grep -c "crates.core" /tmp/build.err >/dev/null
  if grep -q "tlbb-core" /tmp/build.err; then
    echo "attempt $i: 核心 crate 正在被并行会话修改，等待…"
  else
    echo "attempt $i: 自身构建失败"; tail -5 /tmp/build.err; exit 1
  fi
  sleep 20
done
echo "TIMEOUT waiting for core"
exit 1
