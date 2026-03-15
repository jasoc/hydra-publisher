import { Injectable } from '@angular/core';
import { invoke } from '@tauri-apps/api/core';

@Injectable({ providedIn: 'root' })
export class PhotoService {
  async pickFolder(): Promise<string[]> {
    return invoke<string[]>('pick_folder');
  }

  async pickFiles(): Promise<string[]> {
    return invoke<string[]>('pick_files');
  }

  async listPhotosInFolder(path: string): Promise<string[]> {
    return invoke<string[]>('list_photos_in_folder', { path });
  }

  async copyPhotosToArticle(photoPaths: string[], articleFolder: string): Promise<string[]> {
    return invoke<string[]>('copy_photos_to_article', { photoPaths, articleFolder });
  }
}
