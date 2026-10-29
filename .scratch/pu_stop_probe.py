import re,struct,sys
# widths from core table + cls defaults
src=open('tlbb-explorer/crates/core/src/preview/effect.rs',encoding='utf-8').read()
start=src.index('pub(crate) const PARAM_PW'); end=src.index('];',start)
pw={(int(c),int(f)):int(w) for c,f,w in re.findall(r'\((\d+),\s*(\d+),\s*(\d+)\)',src[start:end])}
attrs={}
for line in open('tlbb-explorer/crates/core/data/pu_attr_table.tsv',encoding='utf-8'):
    p=line.strip().split('\t')
    if len(p)==3 and p[0].isdigit(): attrs[int(p[0])]=p[1]
def width(c,f):
    if c==0: return 0
    if c==7: return 3
    if c in (2,3,4,5,11,12,13,15): return 0
    if c==6: return 2
    if c in (8,9,10): return 4
    if c==14: return 5
    if c==17: return 3
    if c==1: return pw.get((1,f),1)
    return pw.get((c,f))
def parse(path):
    raw=open(path,'rb').read()
    if raw[:4]!=b'JBPU': return None
    cnt=struct.unpack_from('<I',raw,4)[0]
    pairs=[struct.unpack_from('<II',raw,8+i*8) for i in range(cnt)]
    p=8+8*cnt; s=[]
    for ln,h in pairs:
        s.append(raw[p:p+ln].decode('latin1')); p+=ln
    ps=(p+3)&~3
    words=[struct.unpack_from('<I',raw,ps+4*i)[0] for i in range((len(raw)-ps)//4)]
    recs=[];q=0;stop=None
    while q<len(words):
        c=(words[q]>>16)&0xffff; f=words[q]&0xffff
        w=width(c,f)
        if w is None:
            stop=(c,f,q,'unknown');break
        if q+1+w>len(words):
            stop=(c,f,q,'overrun');break
        recs.append((q,c,f,w,words[q+1:q+1+w]));q+=1+w
    return {'raw':raw,'ps':ps,'words':words,'recs':recs,'stop':stop,'strings':s}
if __name__=='__main__':
    path=sys.argv[1]
    r=parse(path)
    print('file',path,'ps',r['ps'],'words',len(r['words']),'recs',len(r['recs']),'stop',r['stop'])
    print('last 12 recs:')
    for q,c,f,w,ws in r['recs'][-12:]:
        print(' q=%d cls=%d fld=%d name=%s w=%d words=%s'%(q,c,f,attrs.get(f,'?'),w,' '.join('0x%08x'%x for x in ws)))
    st=r['stop']
    if st:
        c,f,q,why=st
        print('stop key 0x%08x'%r['words'][q] if q<len(r['words']) else 'stop at EOF')
        lo=max(0,q-12); hi=min(len(r['words']),q+12)
        print('words around:', ' '.join('0x%08x'%r['words'][i] for i in range(lo,hi)))
        print('indices:', list(range(lo,hi)))
