fn wrapper_dummy() {
pub fn run() {
    let (root, db) = roots();
    let app = match AppData::open(&root, &db) {
        Ok(a) => a,
        Err(e) => fatal(&e),
    };
    app.warm();

    tauri::Builder::default()
        .manage(Arc::clone(&app))
        .setup(move |handle| {
            let app = Arc::clone(handle.state::<Arc<AppData>>().inner());
            let sink = handle.app_handle().clone();
            let total = app.triage().0;
            std::thread::spawn(move || loop {
                let done = app.ready();
                let _ = sink.emit(
                    "reading",
                    serde_json::json!({ "scanned": app.scanned(), "total": total, "ready": done }),
                );
                if done {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(700));
            });
            Ok(())
        })
}
}
