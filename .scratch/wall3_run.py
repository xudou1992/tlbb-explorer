#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量收料：解 24,261 张无名贴图，出缩略图 + 内容特征。结果落盘供 Read。"""

import subprocess
import time
import os
import re
import shutil
import sys

EXE = r"D:\TLGL\.scratch\rc3\release\deps\wall_harvest.exe"
OUT = r"D:\TLGL\.scratch\wall3"
LOG = r"D:\TLGL\.scratch\_wall_harvest.txt"

lines = []


def say(s):
    print(s, flush=True)
    lines.append(s)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    # 从干净目录开始，避免上次残留混进来
    if os.path.isdir(OUT):
        for sub in ("thumb",):
            p = os.path.join(OUT, sub)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)

    argv = [EXE, "--root=D:/TLGL", "--db=D:/TLGL/.scratch/resources.db",
            "--out=" + OUT, "--thumb=160"]
    say("$ " + " ".join(argv))
    t0 = time.time()
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for raw in p.stdout:
        s = raw.decode("utf-8", errors="replace").rstrip("\n")
        if s.strip():
            say("  " + s)
    p.wait()
    el = time.time() - t0
    say("")
    say("EXIT=%d  墙钟 %.1fs" % (p.returncode, el))

    th = os.path.join(OUT, "thumb")
    n = len(os.listdir(th)) if os.path.isdir(th) else 0
    sz = sum(os.path.getsize(os.path.join(th, f)) for f in os.listdir(th)) if n else 0
    say("缩略图 %d 张 / %.1f MB" % (n, sz / 1048576.0))
    tsv = os.path.join(OUT, "raw.tsv")
    if os.path.exists(tsv):
        say("raw.tsv %.2f MB，%d 行" % (
            os.path.getsize(tsv) / 1048576.0,
            sum(1 for _ in open(tsv, encoding="utf-8")) - 1))


if __name__ == "__main__":
    main()
