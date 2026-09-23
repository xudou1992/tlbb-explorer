import ida_nalt, idautils, idc, re, collections
names=set()
for seg in idautils.Segments():
    s,e=idc.get_segm_name(seg),idc.get_seg_end(seg)
    cur=s
    while cur<e:
        st=ida_nalt.get_str_type(cur)
        if st is not None and st>=0:
            v=idc.get_strlit_contents(cur,-1,st)
            if v:
                try: v=v.decode('utf8','ignore')
                except: v=''
                if v.startswith('.?AV') or v.startswith('.?AU'): names.add(v)
                cur+=len(v)+1 if v else 1
            else: cur+=1
        else: cur+=1
cls=[n[4:] for n in names if n.startswith('.?AV')]
print("RTTI_TOTAL",len(cls))
def base(n):
    n=re.sub(r'@[^@]*$','',n)
    return n
c=collections.Counter()
for n in cls:
    parts=[p for p in n.split('@') if p]
    if len(parts)>=2: c[parts[-2]]+=1
    else: c['<global>']+=1
print("TOP_NAMESPACES")
for k,v in c.most_common(60): print(v,k)
