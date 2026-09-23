#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // `--probe [中文词]` runs the read-only self-check and exits, so the shell can be
    // verified without a window.
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("--probe") => tlbb_shell_lib::probe(args.next()),
        _ => tlbb_shell_lib::run(),
    }
}
