import re, collections, idautils, idc

allstr = [str(s) for s in idautils.Strings()]

out = []
w = out.append


def show(title, pred, lim=25, width=200):
    hits = sorted({s for s in allstr if pred(s)})
    w('')
    w('==== %s  (%d hits) ====' % (title, len(hits)))
    for x in hits[:lim]:
        w('  ' + x[:width])


show('OGRE definitive markers', lambda s: re.search(r'\bOgre|OGRE|ogremain| Ogre::|Ogre\.h|MovableObject|SubEntity\b|HighLevelGpuProgram|ResourceGroupManager|GpuProgramManager|ManualObject|MaterialManager|MeshManager|SceneManager\b|Root\.cpp', s) is not None, 40)
show('PDB paths', lambda s: '.pdb' in s.lower(), 40)
show('source file paths', lambda s: re.search(r'^[A-Za-z]:\\|\\(src|source|engine|code)\\|\.(cpp|h|cc)$', s, re.I) is not None and len(s) < 120, 45)
show('engine codenames', lambda s: re.search(r'Blade|TianMa|天马|Sky\w*Engine|Lance|Goblin|Ejoy|NeoX|ARK3D|Bit16|Wayfinder|Refactor', s) is not None, 30)
show('PhysX / physics', lambda s: re.search(r'physx|PhysX|NpScene|PxPhysics|fabric|Cooking', s) is not None, 25)
show('Factory/Translator/Writer triad', lambda s: re.search(r'(Factory|Translator|Writer)$', s) and len(s) < 45, 40)
show('pak/package/archive', lambda s: re.search(r'JPAK|\.pak|PackageFile|PackageManager|ArchiveStream', s) is not None, 35)
show('network protocol / packet', lambda s: re.search(r'SendRequest|PacketHeader|CmdID|opcode|NetModule|PacketParser|SocketModule', s) is not None, 35)
show('threads', lambda s: re.search(r'Thread', s) and len(s) < 50, 45)

open(r'D:\TLGL\.scratch\ver_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->ver_out.txt')
