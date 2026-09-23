import io,os,re,struct
o=io.open('agent_map_23_jstr.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
miss=['w1351_lyxj_shitouque_001','w1351_fh_qiangzhi_001','w1351_bzd_hongshizhuqi_001','w1351_songliao_dzqiang4s_001']
for fn in ['out/tree/global.jstr','out/tree/binary_table_files_align8_64bit.tab','out/tree/ResourcePath.cfg']:
    if not os.path.exists(fn): W('missing',fn); continue
    raw=open(fn,'rb').read()
    W('\n#### %s size=%d  head=%s'%(fn,len(raw),raw[:32].hex(' ')))
    txt=raw.decode('latin1')
    for m in miss:
        W('   contains %-34s : %s'%(m, m in txt))
    S=re.findall(rb'[\x20-\x7e]{6,}',raw)
    W('   printable runs>=6: %d ; sample: %s'%(len(S),[x.decode('latin1') for x in S[:8]]))
    W('   runs containing .mesh: %d'%sum(1 for x in S if b'.mesh' in x))
    # a known-present mesh for control
    W('   control (a resolvable name) w1351_dl_chengqiang_001 present: %s'%('w1351_dl_chengqiang_001' in txt))
o.close(); print('ok')
