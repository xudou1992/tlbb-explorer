"""地面真相：把同目录 .ske / .ani 里的骨名切出来，与变体判据认到的骨名对账。
.ske 是独立文件、另一套序列化，若两边名字对得上，说明变体记录真的是骨架节点。只读。"""
import os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from variant import v_positions, FIVE, TREE

MODEL = f"{TREE}/data/source/npc/model"
TOKEN = re.compile(rb"[A-Za-z][A-Za-z0-9_]*")
STOP = {b"JBCF"}


def ske_names(d, base):
    """从同目录 .ske/.ani 里捞骨名：按『出现两次即切』的方式取形如 boneNNN / *_bone_NNN 的整串。"""
    got = set()
    for f in os.listdir(d):
        if not f.lower().endswith((".ske", ".ani")):
            continue
        raw = open(os.path.join(d, f), "rb").read()
        for m in re.finditer(rb"[Bb]one[0-9][A-Za-z0-9_]*|fracture_bone_[0-9][A-Za-z0-9_]*|[A-Za-z][A-Za-z0-9]*_bone_[0-9][A-Za-z0-9_]*", raw):
            got.add(m.group().decode())
        # 粘连串拆开：.ske 里骨名是一个接一个紧挨着写的
        for m in re.finditer(rb"[Bb]one[0-9]+", raw):
            pass
    return got


def split_run(raw):
    """把 'bone127bone129bone130' 这类粘连流切成单个 boneNNN。"""
    s = raw.decode("latin-1")
    return [m.group() for m in re.finditer(r"(?:fracture_)?(?:[Bb]one)[0-9]+(?:_[0-9]+)?|bone_bone_[0-9]+|[A-Za-z]+_bone_[0-9]+", s)]


L = []
for k in sorted(FIVE):
    d = os.path.join(MODEL, k[:-5])
    p = os.path.join(d, k)
    raw = open(p, "rb").read()
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    bones = struct.unpack_from("<I", raw, 0x110)[0]
    vp = v_positions(raw, vc)
    # 允许 N=0 的根骨
    from variant import field_name, a_matrix, RUN
    names = set(r["nm"] for r in vp)
    for m in RUN.finditer(raw):
        i = m.start()
        if i % 4:
            continue
        nm = field_name(raw, i)
        if nm is None or field_name(raw, i + 32) != nm or i + 136 > len(raw):
            continue
        if abs(struct.unpack_from("<f", raw, i + 64)[0]) > 1e-3:
            continue
        ok, b, t = a_matrix(raw, i + 68)
        if ok:
            names.add(nm.decode())
    side = set()
    for f in os.listdir(d):
        if f.lower().endswith((".ske", ".ani")):
            r2 = open(os.path.join(d, f), "rb").read()
            side |= set(split_run(r2))
    inter = names & side
    L.append(f"{k}: 判据认到的骨名(含 N=0 根骨) = {len(names)}  头部声明 = {bones}  "
             f"同目录 .ske/.ani 里出现的骨名 = {len(side)}  两边都对上 = {len(inter)}  "
             f"判据有而 .ske 没有 = {sorted(names - side)[:6]}")
    L.append(f"    .ske 有而判据没有（前 8）: {sorted(side - names)[:8]}")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ske_cross.txt"), "w", encoding="utf-8").write("\n".join(L))
print("WROTE ske_cross.txt")
for x in L:
    print(x.encode("unicode_escape").decode()[:190])
