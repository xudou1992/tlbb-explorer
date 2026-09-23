import re, collections, idautils, idc, ida_bytes, ida_segment

out = []
w = out.append

# ---- 1. which DLLs are dynamically loaded, and who loads them ----
dlls = ['webview.dll', 'TMGLibrary.dll', 'GMESDK.dll', 'txffmpeg.dll', 'NEP2_64.dll',
        'd3dcompiler_47.dll', 'iphlpapi.dll', 'wininet.dll', 'version.dll', 'winmm.dll',
        'xinput', 'xaudio', 'oleaut32', 'comdlg32', 'ws2_32', 'opengl32', 'vulkan',
        'dbghelp.dll', 'winhttp', 'urlmon', 'shlwapi', 'powrprof', 'setupapi', 'user32']
w('=== dynamically-referenced DLL strings + their xrefs ===')
for st in idautils.Strings():
    t = str(st)
    low = t.lower()
    if low.endswith('.dll') and len(t) < 60:
        xr = list(idautils.XrefsTo(st.ea))
        frm = ', '.join('%016X:%s' % (x.frm, idc.get_func_name(x.frm)) for x in xr[:3])
        w('  %-42s xrefs=%-3d %s' % (t, len(xr), frm))

# ---- 2. NEP2 call path ----
w('')
w('=== NEP2 import slot & its callers ===')
slot = 0x1411DEF28
w('  slot %016X qword=0x%016X' % (slot, ida_bytes.get_qword(slot)))
for x in list(idautils.XrefsTo(slot))[:20]:
    w('    call from %016X  in %s' % (x.frm, idc.get_func_name(x.frm)))
# who is in the .rdata NEP2 name table
w('  NEP2 name-string xref check:')
n = 0
for st in idautils.Strings():
    t = str(st)
    if t.startswith('NEP2_') and n < 12:
        xr = list(idautils.XrefsTo(st.ea))
        w('    %-34s xrefs=%d %s' % (t, len(xr), ', '.join('%016X' % x.frm for x in xr[:2])))
        n += 1

# ---- 3. .200/.201/.202 identity: printable density + first bytes ----
w('')
w('=== appended sections content probe ===')
for nm in ['.200', '.201', '.202', '.rotext']:
    for s in idautils.Segments():
        if idc.get_segm_name(s) == nm:
            a = ida_segment.getseg(s).start_ea
            b = ida_segment.getseg(s).end_ea
            dat = ida_bytes.get_bytes(a, min(0x4000, b - a)) or b''
            printable = sum(1 for c in dat if 32 <= c < 127) / max(1, len(dat))
            zero = sum(1 for c in dat if c == 0) / max(1, len(dat))
            w('  %-8s %016X-%016X printable=%.2f zero=%.2f' % (nm, a, b, printable, zero))
            strs = re.findall(rb'[ -~]{6,}', dat)[:12]
            for x in strs:
                w('        ' + x.decode()[:100])

open(r'D:\TLGL\.scratch\v6_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->v6_out.txt')
