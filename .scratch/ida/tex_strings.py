import idc, idautils, ida_funcs
out=open(r'D:/TLGL/.scratch/ida/tex_strings_out.txt','w',encoding='utf-8')
keys=['texture','Texture','TEXTURE','LoadTexture','GetTexture','CreateTexture','TexMgr','TextureMgr','LoadFromBinMtlFile','.tga','.dds','JMT1','s_baseMap','s_maskMap','s_dissMap','Material']
seen=set()
for s in idautils.Strings():
    try: t=str(s)
    except: continue
    if t in seen: continue
    if not any(k in t for k in keys): continue
    if len(t)>120: continue
    seen.add(t)
    xr=list(idautils.XrefsTo(s.ea,0))
    funcs=[]
    for x in xr[:8]:
        f=ida_funcs.get_func(x.frm)
        funcs.append(hex(f.start_ea) if f else hex(x.frm))
    out.write('%x\t%r\txrefs=%d\t%s\n'%(s.ea,t,len(xr),','.join(funcs)))
    if len(seen)>500: break
out.close()
idc.qexit(0)
