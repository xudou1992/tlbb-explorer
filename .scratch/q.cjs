const fs=require('fs'),cp=require('child_process');
const SID=fs.readFileSync('D:/TLGL/.scratch/sid.txt','utf8').trim();
const [name, argsJson]=process.argv.slice(2);
const body=JSON.stringify({jsonrpc:'2.0',id:9,method:'tools/call',params:{name,arguments:JSON.parse(argsJson||'{}')}});
const out=cp.execSync(`curl -s -m 180 -X POST http://127.0.0.1:13337/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: ${SID}" -d ${JSON.stringify(body)}`,{maxBuffer:1<<28}).toString();
const j=JSON.parse(out);
if(j.error){console.log('ERR',JSON.stringify(j.error));process.exit(0)}
console.log((j.result.content||[]).map(c=>c.text).join('\n'));
