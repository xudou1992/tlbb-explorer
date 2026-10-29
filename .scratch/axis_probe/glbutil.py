"""Dump the GLB JSON chunk structure so we know how skin/nodes/accessors are laid out."""
import json, struct, sys, pathlib

GLB = pathlib.Path(r"D:\TLGL\.scratch\glb_rigged\m_db18794d0000cd38.glb")

def load_glb(path):
    data = path.read_bytes()
    magic, ver, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x4654_6C67, hex(magic)
    off = 12
    json_chunk = None
    bin_chunk = b""
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        payload = data[off:off+clen]
        off += clen
        if ctype == 0x4E4F_534A:  # 'JSON'
            json_chunk = json.loads(payload.decode("utf-8"))
        elif ctype == 0x004E_4942:  # 'BIN'
            bin_chunk = payload
        else:
            print("unknown chunk", hex(ctype))
    return json_chunk, bin_chunk, magic, ver, length

g, binbuf, magic, ver, length = load_glb(GLB)
print("glb ver", ver, "declared length", length, "file", GLB.stat().st_size)
print("buffers", [(b.get("byteLength"), b.get("type")) for b in g.get("buffers", [])])
print("bin chunk len", len(binbuf))
print("keys", sorted(g.keys()))
print("meshes", [(m.get("name"), [(p.get("name"), p.get("attributes"), p.get("indices"), p.get("material")) for p in m.get("primitives", [])]) for m in g["meshes"]])
print("materials", [m.get("name") for m in g.get("materials", [])])
print("skins", json.dumps(g["skins"], ensure_ascii=False)[:2000])
print("num nodes", len(g["nodes"]))
for i, n in enumerate(g["nodes"]):
    print(i, json.dumps(n, ensure_ascii=False)[:300])
print("accessors:")
for i, a in enumerate(g["accessors"]):
    print(i, a.get("type"), a.get("componentType"), a.get("count"), a.get("byteOffset"), a.get("bufferView"), "min", a.get("min"), "max", a.get("max"), a.get("normalized"))
print("bufferViews:")
for i, bv in enumerate(g["bufferViews"]):
    print(i, bv)
