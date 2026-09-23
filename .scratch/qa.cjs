const fs=require('fs');const SID=fs.readFileSync('D:/TLGL/.scratch/sid.txt','utf8').trim();
const {execSync}=require('child_process');
const a=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const body=JSON.stringify({jsonrpc:'2.0',id:9,method:'tools/call',params:{name:process.argv[3],arguments:a}});
fs.writeFileSync('D:/TLGL/.scratch/body.json',body);
const r=execSync('curl -s -m 300 -X POST http://127.0.0.1:13337/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: '+SID+'" --data-binary @D:/TLGL/.scratch/body.json',{maxBuffer:1<<28}).toString();
try{const j=JSON.parse(r);console.log((j.result&&j.result.content||[]).map(c=>c.text).join('\n')||JSON.stringify(j.error))}catch(e){console.log(r)}
