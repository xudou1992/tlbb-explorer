"""Generate an isolated audit executable from the current browse export functions.

No production sources or game bytes are modified. All writes/junctions go into a
fresh audit sandbox; the original pak and catalog are only read.
"""
import os
import pathlib
import subprocess
import uuid

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
src = (ROOT / 'tlbb-explorer/app/src-tauri/src/browse.rs').read_text(encoding='utf-8')

def between(a, b):
    return src[src.index(a):src.index(b, src.index(a))]

crate = HERE / 'rust-probe'
(crate / 'src').mkdir(parents=True, exist_ok=True)
(crate / 'Cargo.toml').write_text('''[workspace]
[package]
name = "tlgl-audit-probe"
version = "0.0.0"
edition = "2021"
[dependencies]
tlbb-core = { path = "''' + (ROOT / 'tlbb-explorer/crates/core').as_posix() + '''" }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
rusqlite = { version = "0.40.2", features = ["bundled"] }
''', encoding='utf-8')

code = '''// Generated from the current production source by backend-probes.py.
use std::path::{Path,PathBuf};
use std::collections::{HashMap,HashSet};
use std::sync::OnceLock;
use rusqlite::{Connection,OpenFlags};
use serde::Serialize;
use tlbb_core::jpak::{Pak,Record};
use tlbb_core::payload;
fn roots() -> (PathBuf,PathBuf) {
 (std::env::var("AUDIT_CLIENT_ROOT").unwrap().into(), std::env::var("AUDIT_DB").unwrap().into())
}
'''
code += '#[derive(Serialize)]\n' + between('pub struct ExportReport', '// ----------------------------------------------------------------------- 名字表')
code += between('type NameRow', '/// pak 名 → hash')
code += between('const RESERVED_NAMES:', '/// 导出。')
code += between('fn decode_and_write', '// ----------------------------------------------------------------------- 测试')
code += r'''
fn main() {
 let base = PathBuf::from(std::env::var("AUDIT_SANDBOX").unwrap());
 let client = roots().0;
 let out = base.join("out");
 let victim = client.join("protected/effect/effectmodel/w1351_model_emiter_lf002.mesh");
 std::fs::create_dir_all(victim.parent().unwrap()).unwrap();
 std::fs::write(&victim,b"AUDIT-SENTINEL-DO-NOT-OVERWRITE").unwrap();
 // 期望已翻成「修复后」的口径：链接指回客户端根必须被逐文件闸门拦下，
 // 哨兵文件保持原样，written=0、failed 里有一条说明为什么没写。
 // 2026-09-28 修复前的实测是 written=1 / failed=0 / 哨兵被 18408 字节覆盖。
 let report = export_run("data.pak", &["401e639268cc7a0c".into()],out.to_str().unwrap(),&|_|{}).unwrap();
 let bytes = std::fs::read(&victim).unwrap();
 assert_eq!(report.written,0,"junction 指回客户端根时不得写盘成功");
 assert_eq!(report.failed.len(),1,"应如实记一条失败，实际：{:?}",report.failed);
 assert_eq!(bytes,b"AUDIT-SENTINEL-DO-NOT-OVERWRITE","客户端目录里的哨兵被改写了");
 println!("PASS export: junction into client root blocked; sentinel intact, failed={:?}",report.failed);
 let original_root = PathBuf::from(std::env::var("AUDIT_ORIGINAL_ROOT").unwrap());
 for (name,pak,hash) in [
  ("w1351_model_emiter_lf002.mesh","data",0x401e639268cc7a0cu64),
  ("w1351_model_emiter_lf004.mesh","data3",0x6c772610af35e0d2u64)
 ] {
  let p=Pak::open(original_root.join(format!("{pak}.pak"))).unwrap();
  let r=p.records().find(|r|r.hash==hash && r.stored>0).unwrap();
  let raw=payload::decode(&p,&r).unwrap().bytes;
  let mesh=tlbb_core::preview::geometry::parse_mesh(&raw).unwrap();
  let fixture=std::fs::read(original_root.join("tlbb-explorer/crates/core/tests").join(name)).unwrap();
  let lossy=String::from_utf8_lossy(&raw).as_bytes().to_vec();
  println!("FIXTURE {name}: actual={} local={} UTF8_lossy_equal={} parse_ok vertices={} faces={:?}",raw.len(),fixture.len(),lossy==fixture,mesh.geometry.vertex_count,mesh.face_counts);
 }
}
'''
(crate / 'src/main.rs').write_text(code, encoding='utf-8')
base = HERE / 'sandbox' / uuid.uuid4().hex
client = base / 'client'
(client / 'protected').mkdir(parents=True)
(base / 'out').mkdir()
os.link(ROOT / 'data.pak', client / 'data.pak')  # read-only input; no 1 GB copy
subprocess.run(['powershell', '-NoProfile', '-Command',
                "New-Item -ItemType Junction -Path '" + str(base / 'out/data') +
                "' -Target '" + str(client / 'protected') + "' | Out-Null"], check=True)
env = os.environ.copy()
env.update(AUDIT_CLIENT_ROOT=str(client), AUDIT_DB=str(ROOT / '.scratch/resources.db'),
           AUDIT_SANDBOX=str(base), AUDIT_ORIGINAL_ROOT=str(ROOT),
           CARGO_TARGET_DIR=str(ROOT / 'tlbb-explorer/target'))
result = subprocess.run(['cargo', 'run', '--offline', '--manifest-path', str(crate / 'Cargo.toml')], env=env)
print('Isolated sandbox:', base)
raise SystemExit(result.returncode)
