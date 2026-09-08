// Zero OS — Tauri Desktop Shell
// Frameless transparent window wrapping the neural HUD frontend.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_http::init())
        .run(tauri::generate_context!())
        .expect("error while running Zero OS");
}
