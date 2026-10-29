import fs from 'fs';
const p=process.argv[2], label=process.argv[3];
const b=fs.readFileSync(p);
const vc=b.readUInt32LE(0x8C),fc=b.readUInt32LE(0x90),smf=b.readUInt32LE(0x94),sm=smf||1;
const posEnd=0x118+vc*12, uvAt=posEnd+vc*12;
const idxAt=uvAt+vc*8+fc*2, ip=idxAt+4*sm;
const P=k=>[b.readFloatLE(0x118+k*12),b.readFloatLE(0x118+k*12+4),b.readFloatLE(0x118+k*12+8)];
const w=(k,i)=>b.readUInt16LE(uvAt+k*8+i*2);
const decs={
 f32_le:(k)=>[b.readFloatLE(uvAt+k*8),b.readFloatLE(uvAt+k*8+4)],
 f32_be:(k)=>[b.readFloatBE(uvAt+k*8),b.readFloatBE(uvAt+k*8+4)],
 u16le_p01:(k)=>[w(k,0)/65535,w(k,1)/65535],
 u16le_p23:(k)=>[w(k,2)/65535,w(k,3)/65535],
 u16le_02:(k)=>[w(k,0)/65535,w(k,2)/65535],
 u16le_13:(k)=>[w(k,1)/65535,w(k,3)/65535],
 u16be_p01:(k)=>[b.readUInt16BE(uvAt+k*8)/65535,b.readUInt16BE(uvAt+k*8+2)/65535],
 u16be_p23:(k)=>[b.readUInt16BE(uvAt+k*8+4)/65535,b.readUInt16BE(uvAt+k*8+6)/65535],
 u16be_02:(k)=>[b.readUInt16BE(uvAt+k*8)/65535,b.readUInt16BE(uvAt+k*8+4)/65535],
 u16be_13:(k)=>[b.readUInt16BE(uvAt+k*8+2)/65535,b.readUInt16BE(uvAt+k*8+6)/65535],
};
function metrics(uv){
  const dot=(a,c)=>a[0]*c[0]+a[1]*c[1]+a[2]*c[2];
  const sub=(a,c)=>[a[0]-c[0],a[1]-c[1],a[2]-c[2]];
  const cross=(a,c)=>[a[1]*c[2]-a[2]*c[1],a[2]*c[0]-a[0]*c[2],a[0]*c[1]-a[1]*c[0]];
  const nrm=a=>Math.hypot(...a);
  const ratios=[],conf=[],corrX=[],corrY=[];
  const step=Math.max(1,Math.floor(fc/4000));
  let used=0;
  for(let f=0;f<fc;f+=step){
    const t=[b.readUInt16LE(ip+f*6),b.readUInt16LE(ip+f*6+2),b.readUInt16LE(ip+f*6+4)];
    const q=t.map(uv), pp=t.map(P);
    if(!q.every(v=>Number.isFinite(v[0])&&Number.isFinite(v[1]))) continue;
    if(q.every(v=>Math.abs(v[0])<1e-9&&Math.abs(v[1])<1e-9)) continue;
    const p0=pp[0],e1=sub(pp[1],p0),e2=sub(pp[2],p0),n=cross(e1,e2),nl=nrm(n);
    if(!nl||!Number.isFinite(nl)) continue;
    const nn=n.map(x=>x/nl);
    const u1=e1; const u2=cross(nn,u1);
    const a1=[dot(e1,u1),dot(e1,u2)], a2=[dot(e2,u1),dot(e2,u2)];
    const det=a1[0]*a2[1]-a1[1]*a2[0]; if(Math.abs(det)<1e-12) continue;
    const b1=[q[1][0]-q[0][0],q[1][1]-q[0][1]], b2=[q[2][0]-q[0][0],q[2][1]-q[0][1]];
    const m00=(b1[0]*a2[1]-b2[0]*a1[1])/det, m01=(b2[0]*a1[0]-b1[0]*a2[0])/det;
    const m10=(b1[1]*a2[1]-b2[1]*a1[1])/det, m11=(b2[1]*a1[0]-b1[1]*a2[0])/det;
    const E=m00*m00+m01*m01,F=m00*m10+m01*m11,G=m10*m10+m11*m11;
    const tr=E+G,dt=E*G-F*F,disc=Math.sqrt(Math.max(0,tr*tr/4-dt));
    const s1=Math.sqrt(Math.max(1e-30,tr/2+disc)),s2=Math.sqrt(Math.max(1e-30,tr/2-disc));
    ratios.push(s1/s2);
    // uv area / 3d area (both as triangle areas)
    const uvA=Math.abs((b1[0]*b2[1]-b1[1]*b2[0]))/2;
    const a3=nl/2;
    if(a3>1e-12) conf.push(uvA/a3);
    // edge length correlation sample
    for(let e=0;e<3;e++){const A=t[e],B=t[(e+1)%3];const d3=nrm(sub(P(B),P(A)));const qa=uv(A),qb=uv(B);const du=Math.hypot(qa[0]-qb[0],qa[1]-qb[1]);if(d3>1e-6&&Number.isFinite(du)){corrX.push(Math.log(d3));corrY.push(Math.log(Math.max(du,1e-12)));}}
    used++;
  }
  const pct=(arr,q)=>{if(!arr.length)return NaN;const a=arr.slice().sort((x,y)=>x-y);return a[Math.min(a.length-1,Math.floor(q*(a.length-1)))];};
  const medRatio=pct(ratios,.5), p99Ratio=pct(ratios,.99);
  let mx=0,my=0; for(const v of corrX)mx+=v; mx/=corrX.length;
  let myy=0; for(const v of corrY)myy+=v; myy/=corrY.length;
  let sxy=0,sxx=0,syy=0; for(let i=0;i<corrX.length;i++){const dx=corrX[i]-mx,dy=corrY[i]-myy;sxy+=dx*dy;sxx+=dx*dx;syy+=dy*dy;}
  return {used,confMed:pct(ratios,.5),confP99:p99Ratio,areaP95:pct(conf,.95),corr:sxy/Math.sqrt(sxx*syy||1)};
}
console.log('==',label);
for(const [name,uv] of Object.entries(decs)){
  const m=metrics(uv);
  console.log(name.padEnd(12), JSON.stringify(Object.fromEntries(Object.entries(m).map(([k,v])=>[k,Number.isFinite(v)?+v.toFixed(3):v]))));
}
