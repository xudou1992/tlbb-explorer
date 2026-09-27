mod marker {}
fn f() -> () {
    let g = Tauri::default()
        .invoke_handler(tauri::generate_handler![
            a,
            b::c,
            d::e,
            f1::f2
        ])
        .run(tauri::generate_context!())
        .expect("x");
}
