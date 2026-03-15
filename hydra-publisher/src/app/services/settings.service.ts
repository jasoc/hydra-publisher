import { Injectable, signal } from '@angular/core';
import { invoke } from '@tauri-apps/api/core';
import { AppSettings } from '../models/settings.model';

@Injectable({ providedIn: 'root' })
export class SettingsService {
  private settingsSignal = signal<AppSettings | null>(null);
  readonly settings = this.settingsSignal.asReadonly();

  async load(): Promise<AppSettings> {
    const settings = await invoke<AppSettings>('get_settings');
    this.settingsSignal.set(settings);
    return settings;
  }

  async save(settings: AppSettings): Promise<void> {
    await invoke('save_settings', { settings });
    this.settingsSignal.set(settings);
  }
}
