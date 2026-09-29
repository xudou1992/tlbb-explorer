//! 后台批量试贴（v0.4.1）：把 `uvfit_batch` 命令行工具变成工作台自己会跑的一件事。
//!
//! 为什么要有这一层：贴图候选榜来自「全库批量试贴」的落盘结果，之前只能人在
//! 终端前敲命令才有。用户点开一只模型看到 🔴（没有候选缓存）时，缺的从来不是
//! 数据而是「这轮批量还没跑」。现在界面里就能发起，进度走 `textureWarming` 事件。
//!
//! 只读纪律与引擎一致：db 只读、pak 只读，只写 `.scratch/uvfit_batch/`。
//! 引擎是增量幂等的（评过的跳过），所以重复点击不会重算全库。

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde_json::json;
use tauri::Emitter;
use tlbb_core::preview::uvfit_batch::{self, Config};

/// 有没有在跑。同一份全库榜并行跑两次只会互相抢内存带宽与写同一批文件，
/// 所以只许一个：第二个请求直接回「已经在跑了」。
static RUNNING: AtomicBool = AtomicBool::new(false);
/// 上一轮跑完的账面（total/scored/pool/elapsedSec…）。没跑过就是 None，
/// 前端据此区分「没跑过」和「跑过但没结果」。
static LAST: Mutex<Option<serde_json::Value>> = Mutex::new(None);

fn cfg() -> Config {
    let (root, db) = crate::inspector::roots();
    Config::for_client(root, db)
}

/// 现在能不能发起、还差多少只模型、上一轮的账面。
///
/// `pending` 是 None 时说的是「数不出来」（本机没有资源清单库），不是「0 只」——
/// 前端不许把数不出来写成「都跑完了」。
#[tauri::command]
pub fn texture_warm_status() -> serde_json::Value {
    let c = cfg();
    json!({
        "running": RUNNING.load(Ordering::Relaxed),
        "pending": pending_of(&c),
        "last": LAST.lock().unwrap().clone(),
    })
}

fn pending_of(c: &Config) -> Option<usize> {
    uvfit_batch::pending(c)
}

/// 后台跑批量试贴。已经在跑就回一句话，不起第二个。
/// 命令立刻返回（跑在阻塞线程池里），进度从 `textureWarming` 事件出来：
/// `{phase:"pool"|"scored",done,total,...}`，收尾一条 `{phase:"finished",...}`。
#[tauri::command]
pub async fn texture_warm_start(app: tauri::AppHandle) -> Result<&'static str, String> {
    if RUNNING.swap(true, Ordering::SeqCst) {
        return Ok("批量试贴已经在后台跑了");
    }
    tauri::async_runtime::spawn_blocking(move || {
        let c = cfg();
        // 节流：池解码一次要发 1,650 条、全库评分要发 2,818 条，逐条 emit 会把
        // IPC 淹掉。按条数抽稀（评分每 25 只、池每 200 张），收尾必发 finished。
        // 不用「距上次多少毫秒」那种闸：那要一个可变的计时器，而进度闭包要
        // Fn + Sync（分片线程也在汇报）——抽稀只抽进度，不抽账面。
        let progress = {
            let sink = app.clone();
            move |v: serde_json::Value| {
                let phase = v["phase"].as_str().unwrap_or("");
                let done = v["done"].as_u64().unwrap_or(0) as usize;
                let emit = phase == "finished"
                    || (phase == "scored" && done % 25 == 0)
                    || (phase == "pool" && done % 200 == 0);
                if emit {
                    let _ = sink.emit("textureWarming", v);
                }
            }
        };
        let out = uvfit_batch::run(&c, &progress);
        RUNNING.store(false, Ordering::SeqCst);
        match out {
            Ok(s) => {
                if let Ok(mut g) = LAST.lock() {
                    *g = serde_json::to_value(&s).ok();
                }
            }
            Err(e) => {
                let _ = app.emit("textureWarming", json!({ "phase": "error", "error": e }));
            }
        }
    });
    Ok("已开始后台批量试贴")
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 回包体检：这条命令是界面唯一的信息来源，字段少了前端就会哑巴。
    /// 有清单的机器上 pending 必须是「一个数」，不能是 null；没清单的机器上
    /// 必须是 null（=数不出来），两种都不许塌成 0——0 会被界面读成「都跑完了」。
    #[test]
    fn 状态回包区分得出借不到与跑完了() {
        let v = texture_warm_status();
        assert_eq!(v["running"].as_bool(), Some(false), "没有别的用例在跑，起始必须是没在跑");
        assert!(v["last"].is_null(), "本进程没跑过，last 就该是 null");
        let pending = &v["pending"];
        if std::env::var("TLBB_DB").map(std::path::PathBuf::from).is_ok_and(|p| p.is_file())
            || crate::inspector::roots().1.is_file()
        {
            assert!(pending.is_number(), "有资源清单时 pending 必须是数字，实际：{pending}");
        } else {
            assert!(pending.is_null(), "没有清单时 pending 必须是 null（数不出来），不是 0");
        }
    }
}
