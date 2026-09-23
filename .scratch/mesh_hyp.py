import struct, traceback

def load(name):
    return open(r"D:\TLGL\.scratch\meshbin_%s.bin" % name.replace('/', '_'), "rb").read()

names = [
    "w1351_model_plane_c01.mesh",
    "w1351_model_mianpian_l001.mesh",
    "w1351_model_fuwenzi_l001.mesh",
    "w1351_model_t_canying_h004.mesh",
    "w1351_monster_xiyuqiezei_yifu_001.mesh",
    "test_jianzhen.mesh",
    "w1351_st_fwzhongxing_001.mesh",
]
rep = []
try:
    for n in names:
        d = load(n)
        vc, fc, m0 = struct.unpack_from("<3I", d, 0x8C)
        f114 = struct.unpack_from("<I", d, 0x114)[0] if len(d) > 0x118 else -1
        tail_fc = struct.unpack_from("<I", d, len(d) - 16)[0] if len(d) >= 20 else -1
        f = struct.unpack_from("<9f", d, 0x118) if len(d) >= 0x118 + 36 else ()
        rep.append("%-44s size=%-8d 0x8C=%-8d 0x90=%-7d 0x94=%-4d 0x114=%-8d tail_fc=%d" %
                   (n.split('/')[-1], len(d), vc, fc, m0, f114, tail_fc))
        rep.append("    f32@0x118: %s" % (tuple(round(x, 3) for x in f),))
except Exception:
    rep.append(traceback.format_exc())
open(r"D:\TLGL\.scratch\mesh_hyp.txt", "w", encoding="utf-8").write("\n".join(rep))
print("done")
