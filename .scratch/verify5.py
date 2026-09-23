import re, collections, idautils, idc, ida_bytes, ida_name, ida_segment

out = []
w = out.append

# 1) entry chain
w('=== entry chain ===')
for ea in [0x140AC2A38, 0x141250594, 0x1412506CC]:
    f = idc.get_func_name(idc.get_func_attr(ea, idc.FUNCATTR_START))
    w('  %016X in %s' % (ea, f))
for ea in [0x140AC2A38]:
    for i in range(4):
        n = idc.next_head(ea)
        w('    %s' % idc.generate_disasm_line(ea, 0))
        ea = n

# 2) .202 section: what lives there
s202 = None
for s in idautils.Segments():
    if idc.get_segm_name(s) == '.202':
        s202 = (ida_segment.getseg(s).start_ea, ida_segment.getseg(s).end_ea)
w('')
w('=== .202 %s ===' % (s202 and ('%016X-%016X' % s202)))
if s202:
    fns = list(idautils.Functions(s202[0], s202[1]))
    w('functions: %d' % len(fns))
    for f in fns[:25]:
        w('   %016X %s' % (f, idc.get_func_name(f)))

# 3) Lua C API presence (statically linked Lua?)
w('')
w('=== Lua C API symbols ===')
lua_api = ['luaL_newstate', 'lua_pcallk', 'lua_setfield', 'lua_getfield', 'lua_pushlstring',
           'luaopen_base', 'lua_createtable', 'luaL_checkinteger', 'lua_tolength', 'lua_rawgetp',
           'luaB_pcall', 'luaD_precall', 'luaV_execute', 'luaS_new', 'f_parser']
for nm in lua_api:
    ea = idc.get_name_ea_simple(nm)
    w('  %-22s %s' % (nm, '%016X' % ea if ea != idc.BADADDR else '-'))
# any names containing lua
c = collections.Counter()
for ea in idautils.Functions():
    n = idc.get_func_name(ea)
    if re.match(r'^(lua|luaL|luaB|luaT|luaD|luaV|luaS|lapi|ldo|lfunc|lgc|lmem|lobject|lstate|string|table)_?', n):
        c[re.match(r'^[a-zA-Z]+', n).group(0)] += 1
w('  lua-prefixed function name roots: %s' % dict(c))

# 4) threading model from UI/App log strings
w('')
w('=== thread / loop / fps strings ===')
for st in idautils.Strings():
    t = str(st)
    if re.search(r'(Thread|tick|Tick|FrameRate|FPS|MainLoop|GameLoop|RenderLoop|Sleep\(|heartbeat)', t) and len(t) < 90 and not t.startswith('.?AV'):
        w('  ' + t)

open(r'D:\TLGL\.scratch\v5_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->v5_out.txt')
