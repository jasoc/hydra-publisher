use std::path::Path;
use tauri::AppHandle;
use tauri_plugin_dialog::DialogExt;

const IMAGE_EXTENSIONS: &[&str] = &["jpg", "jpeg", "png", "webp", "heic", "bmp", "gif"];
const VIDEO_EXTENSIONS: &[&str] = &["mp4", "mov", "avi", "mkv", "webm"];

fn is_media_file(path: &Path, extensions: &[&str]) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| extensions.contains(&e.to_lowercase().as_str()))
        .unwrap_or(false)
}

#[tauri::command]
pub async fn pick_folder(app: AppHandle) -> Result<Vec<String>, String> {
    let folder = app
        .dialog()
        .file()
        .set_title("Select photo folder")
        .blocking_pick_folder();

    match folder {
        Some(path) => {
            let dir = path.as_path().ok_or("Invalid folder path")?;
            list_photos_in_folder(dir.to_string_lossy().to_string()).await
        }
        None => Ok(Vec::new()),
    }
}

#[tauri::command]
pub async fn pick_files(app: AppHandle) -> Result<Vec<String>, String> {
    let files = app
        .dialog()
        .file()
        .set_title("Select photos")
        .add_filter("Images", &["jpg", "jpeg", "png", "webp", "heic", "bmp", "gif"])
        .add_filter("Videos", &["mp4", "mov", "avi", "mkv", "webm"])
        .blocking_pick_files();

    match files {
        Some(paths) => Ok(paths
            .iter()
            .filter_map(|p| p.as_path().map(|p| p.to_string_lossy().to_string()))
            .collect()),
        None => Ok(Vec::new()),
    }
}

#[tauri::command]
pub async fn list_photos_in_folder(path: String) -> Result<Vec<String>, String> {
    let dir = Path::new(&path);
    if !dir.is_dir() {
        return Err(format!("{} is not a directory", path));
    }

    let mut files = Vec::new();
    let entries = std::fs::read_dir(dir).map_err(|e| e.to_string())?;

    for entry in entries {
        let entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path();
        if path.is_file() && (is_media_file(&path, IMAGE_EXTENSIONS) || is_media_file(&path, VIDEO_EXTENSIONS)) {
            files.push(path.to_string_lossy().to_string());
        }
    }

    files.sort();
    Ok(files)
}

#[tauri::command]
pub async fn copy_photos_to_article(
    photo_paths: Vec<String>,
    article_folder: String,
) -> Result<Vec<String>, String> {
    let dest = Path::new(&article_folder);
    if !dest.is_dir() {
        return Err(format!("{} is not a directory", article_folder));
    }

    let mut filenames = Vec::new();
    for src_path in &photo_paths {
        let src = Path::new(src_path);
        let filename = src
            .file_name()
            .ok_or_else(|| format!("Invalid filename: {}", src_path))?;
        let dest_file = dest.join(filename);

        // Handle name collision by appending a number
        let final_dest = if dest_file.exists() {
            let stem = src.file_stem().unwrap_or_default().to_string_lossy();
            let ext = src.extension().unwrap_or_default().to_string_lossy();
            let mut counter = 1;
            loop {
                let new_name = format!("{}_{}.{}", stem, counter, ext);
                let candidate = dest.join(&new_name);
                if !candidate.exists() {
                    break candidate;
                }
                counter += 1;
            }
        } else {
            dest_file
        };

        std::fs::copy(src, &final_dest).map_err(|e| e.to_string())?;
        filenames.push(
            final_dest
                .file_name()
                .unwrap()
                .to_string_lossy()
                .to_string(),
        );
    }

    Ok(filenames)
}
