#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待命钩子驱动：先起这个，再由你启动客户端；进程一出现就 attach，表建起来了就自己 dump。

为什么要它：`qword_1410B5C38`（类型注册表）与 `qword_1410A7DD8`（工厂对象）都是**运行期**才写的，
静态库里全是 0xFFFFFFFFFFFFFFFF，IDB 拿不到（2026-10-10 四枪判死，见
`.scratch/ida/mesh装载器_线索_20261010.md`）。动态一次就够。

默认全自动：探测到非空桶就 dump 整表 + 挂 create + 写报告后退出，你只需要
「先起这个脚本，再开客户端，玩到能看见一只怪」。
按键（前台跑着才能敲）：p 探测 / d 整表 dump / c 挂 create / q 退出。

Windows 上 frida 没有子进程门控（enable_spawn_gating 直接抛 NotSupportedError），
所以用「出生轮询」：先记已存在的同名 pid，20ms 一次等新 pid 出现立刻 attach。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    import frida
except ImportError:
    print("缺 frida：pip install frida-tools 或 pip install frida")
    sys.exit(1)

HERE = Path(__file__).resolve().parent
JS = HERE / "dump_types.js"
OUT = HERE / "out"
BUCKET_CAP = 0x20000
# frida 17：模块级的 frida.enumerate_processes() 已经没了，一律走 device。
DEV = frida.get_local_device()


def pids(name):
    return {p.pid for p in DEV.enumerate_processes() if name.lower() in (p.name or "").lower()}


def wait_birth(name, before, timeout, quiet=False):
    """等一个新出现的同名进程；已有的一律不算（避免挂到上一局还活着的窗口）。"""
    t0 = time.time()
    last_beat = 0
    while time.time() - t0 < timeout:
        now = pids(name)
        fresh = sorted(now - before)
        if fresh:
            # 工作集过滤僵尸：刚出生的进程可能瞬间退掉
            for pid in fresh:
                try:
                    sess = DEV.attach(pid)
                except Exception as e:
                    if not quiet:
                        print(f"  pid {pid} attach 失败（{e}），继续等")
                    continue
                return pid, sess
        if not quiet and time.time() - last_beat > 5:
            last_beat = time.time()
            print(f"  等「{name}」出生…已等 {int(time.time()-t0)} 秒（现在同名进程：{sorted(now)}）")
        time.sleep(0.02)
    raise TimeoutError(f"{timeout} 秒内没等到「{name}」")


class Session:
    def __init__(self, sess, pid, name):
        self.pid = pid
        self.name = name
        self.script = sess.create_script(JS.read_text(encoding="utf-8"))
        self.messages = []
        self.creates = []
        self.session = sess

        def on_msg(msg, data):
            if msg.get("type") == "send":
                p = msg.get("payload") or {}
                self.messages.append(p)
                if p.get("kind") == "create":
                    self.creates.append(p)
                else:
                    print("  [js]", json.dumps(p, ensure_ascii=False)[:220])
            else:
                print("  [js 错]", json.dumps(msg, ensure_ascii=False)[:300])
                self.messages.append({"kind": "error", "msg": msg})

        self.script.on("message", on_msg)
        self.script.load()

    def rpc(self):
        return self.script.exports_sync

    def probe(self):
        r = self.rpc().probe()
        print("  探测：", json.dumps(r, ensure_ascii=False)[:200])
        return r or {}

    def dump(self, limit=40):
        r = self.rpc().dump(limit)
        return r or {}

    def hook_create(self):
        r = self.rpc().hook_create()
        print("  挂 create：", json.dumps(r, ensure_ascii=False)[:200])
        return r or {}

    def finish(self, tag, result):
        OUT.mkdir(parents=True, exist_ok=True)
        stem = OUT / f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}"
        stem.with_suffix(".json").write_text(
            json.dumps({"result": result, "messages": self.messages, "creates": self.creates[:400]},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        reg = (result or {}).get("registry") or {}
        fac = (result or {}).get("factory") or {}
        lines = [f"# 动态取表 · {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        lines += [f"- 进程：{self.name} pid={self.pid}",
                  f"- 桶数组非空节点：**{reg.get('nonEmpty', '没数到')}** / {BUCKET_CAP}，名字解析成功 **{reg.get('parsed', 0)}**",
                  f"- 名字指针偏移命中：{json.dumps(reg.get('offHits', {}), ensure_ascii=False)}",
                  f"- 工厂：{json.dumps(fac, ensure_ascii=False)}",
                  f"- create 记录条数：{len(self.creates)}",
                  f"- 原始 json：{stem.with_suffix('.json')}"]
        if reg.get("err"):
            lines += ["", f"**没拿到的部分**：{reg['err']}"]
        samples = reg.get("samples") or []
        if samples:
            lines += ["", "## 前若干条节点", ""]
            for s in samples[:60]:
                lines.append(f"- {json.dumps(s, ensure_ascii=False)}")
        stem.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        print(f"报告：{stem}.md / {stem}.json")
        return stem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="tlbbgl_x64", help="进程名子串（自测可填 notepad）")
    ap.add_argument("--timeout", type=int, default=900, help="等多久出生（秒）")
    ap.add_argument("--auto", action="store_true", default=True, help="探测到表建好就自动 dump 并退出")
    ap.add_argument("--no-auto", dest="auto", action="store_false")
    ap.add_argument("--selftest", action="store_true", help="自己拉一个 notepad 走一遍出生轮询与 attach")
    ap.add_argument("--probe-interval", type=float, default=5.0)
    args = ap.parse_args()

    js_ok = JS.is_file()
    print(f"payload：{JS} （{'在' if js_ok else '★缺文件'}）")
    if not js_ok:
        return 2

    spawn = None
    if args.selftest:
        known = pids(args.name)
        print(f"自测：拉起 notepad（同名已有 {sorted(known)}，应当挂到新的那个）")
        spawn = subprocess.Popen(["notepad.exe"])
        before = known
    else:
        before = pids(args.name)
        print(f"已在运行的同名进程（这些一律不挂）：{sorted(before) or '没有'}")

    pid, sess = wait_birth(args.name, before, args.timeout)
    print(f"挂上了：pid {pid}")
    s = Session(sess, pid, args.name)
    st = s.rpc().status()
    print("  status：", json.dumps(st, ensure_ascii=False)[:240])

    result = None
    if args.selftest:
        # 自测只验管道：出生轮询、attach、payload 装载、RPC、报告落盘。
        # 客户端不存在，所以每一次取数都该「老实说读不到」而不是崩掉——这正是要验的那条。
        print("  自测探测：", json.dumps(s.probe(), ensure_ascii=False)[:200])
        s.hook_create()
        s.finish("selftest", s.dump(5))
        try:
            sess.detach()
        except Exception:
            pass
        if spawn is not None:
            spawn.terminate()
            print("（自测的 notepad 已收掉）")
        return 0
    if args.auto:
        t0 = time.time()
        while time.time() - t0 < 1800:
            r = s.probe()
            if r.get("built"):
                break
            time.sleep(args.probe_interval)
        else:
            print("  30 分钟还没等到表建起来（客户端没跑到能显示怪？）")
        s.hook_create()
        result = s.dump(40)
        tag = "types" if not args.selftest else "selftest"
        s.finish(tag, result)
    else:
        print("按键：p 探测 / d 整表 dump / c 挂 create / q 退出")
        while True:
            try:
                k = input("> ").strip().lower()
            except EOFError:
                break
            if k == "q":
                break
            if k == "p":
                s.probe()
            elif k == "d":
                s.finish("types", s.dump(40))
            elif k == "c":
                s.hook_create()
    try:
        sess.detach()
    except Exception:
        pass
    if spawn is not None:
        spawn.terminate()
        print("（自测的 notepad 已收掉）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
