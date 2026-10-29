import sys, json, time, frida
def main():
    pid = int(sys.argv[1])
    js = open(r"D:\TLGL\.scratch\hook\mesh_probe.js", encoding="utf-8").read()
    dev = frida.get_local_device()
    print("attach ->", pid, flush=True)
    s = dev.attach(pid)
    sc = s.create_script(js)
    logs = []
    sc.on("message", lambda m, d: logs.append(m))
    sc.load()
    time.sleep(0.5)
    print("loaded, logs:", json.dumps([l.get("payload") for l in logs if l.get("type")=="log"], ensure_ascii=False), flush=True)
    mods = sc.exports_sync.modules("tlbbgl|engine|gfx|fantasy")
    print("modules:", json.dumps(mods, ensure_ascii=False)[:1200], flush=True)
    s.detach()
    print("detached", flush=True)
main()
