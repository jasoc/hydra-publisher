mod commands;
mod models;
mod state;

use state::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            commands::settings::get_settings,
            commands::settings::save_settings,
            commands::photos::pick_folder,
            commands::photos::pick_files,
            commands::photos::list_photos_in_folder,
            commands::photos::copy_photos_to_article,
            commands::catalog::create_article,
            commands::catalog::list_articles,
            commands::catalog::get_article,
            commands::catalog::update_article,
            commands::catalog::delete_article,
            commands::ai::start_ai_fill,
            commands::ai::get_ai_requests,
            commands::publish::list_platforms,
            commands::publish::publish_articles,
            commands::publish::get_publish_records,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
