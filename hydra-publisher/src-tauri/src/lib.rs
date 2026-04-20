mod commands;
mod models;
mod state;

use state::AppState;
use tauri::Manager;
use tauri_plugin_store::StoreExt;
use crate::models::platform::PublishRecord;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .manage(AppState::default())
        .setup(|app| {
            // Restore publish records persisted from the previous session.
            let store = app.store("publish_records.json")?;
            if let Some(val) = store.get("records") {
                if let Ok(records) = serde_json::from_value::<Vec<PublishRecord>>(val.clone()) {
                    let state = app.state::<AppState>();
                    if let Ok(mut guard) = state.publish_records.lock() {
                        *guard = records;
                    };
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::settings::get_settings,
            commands::settings::save_settings,
            commands::settings::fetch_ebay_policies,
            commands::settings::search_ebay_categories,
            commands::photos::pick_folder,
            commands::photos::pick_files,
            commands::photos::list_photos_in_folder,
            commands::photos::copy_photos_to_article,
            commands::catalog::create_article,
            commands::catalog::list_articles,
            commands::catalog::get_article,
            commands::catalog::update_article,
            commands::catalog::delete_article,
            commands::catalog::clear_all_app_data,
            commands::ai::start_ai_fill,
            commands::ai::get_ai_requests,
            commands::ai::regenerate_article_fields,
            commands::publish::list_platforms,
            commands::publish::publish_articles,
            commands::publish::get_publish_records,
            commands::publish::update_articles,
            commands::publish::delete_ebay_offer,
            commands::publish::retry_publish,
            commands::publish::open_provider_session,
            commands::publish::force_reset_task,
            commands::publish::get_active_sessions,
            commands::publish::kill_session,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
