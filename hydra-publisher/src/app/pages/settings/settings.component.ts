import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { SettingsService } from '../../services/settings.service';
import { AppSettings } from '../../models/settings.model';
import { invoke } from '@tauri-apps/api/core';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule,
    MatSnackBarModule,
  ],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss',
})
export class SettingsComponent implements OnInit {
  loading = signal(false);

  catalogRoot = '';
  aiHost = '';
  aiToken = '';
  aiModel = '';
  language = '';
  enabledPlatforms: string[] = ['subito', 'facebook_marketplace', 'vinted'];

  seleniumLoginPlatforms = [
    { id: 'facebook_marketplace', name: 'Facebook Marketplace' },
    { id: 'vinted', name: 'Vinted' },
    { id: 'subito', name: 'Subito.it' },
  ];

  allPlatforms = [
    { id: 'subito', name: 'Subito.it' },
    { id: 'facebook_marketplace', name: 'Facebook Marketplace' },
    { id: 'vinted', name: 'Vinted' },
  ];

  isPlatformEnabled(id: string): boolean {
    return this.enabledPlatforms.includes(id);
  }

  togglePlatform(id: string): void {
    if (this.enabledPlatforms.includes(id)) {
      this.enabledPlatforms = this.enabledPlatforms.filter(p => p !== id);
    } else {
      this.enabledPlatforms = [...this.enabledPlatforms, id];
    }
  }

  languages = [
    { value: 'en', label: 'English' },
    { value: 'it', label: 'Italian' },
    { value: 'fr', label: 'French' },
    { value: 'de', label: 'German' },
    { value: 'es', label: 'Spanish' },
    { value: 'pt', label: 'Portuguese' },
  ];

  constructor(
    private settingsService: SettingsService,
    private snackBar: MatSnackBar,
  ) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      const settings = await this.settingsService.load();
      this.catalogRoot = settings.catalogRoot;
      this.aiHost = settings.aiHost;
      this.aiToken = settings.aiToken;
      this.aiModel = settings.aiModel;
      this.language = settings.language;
      this.enabledPlatforms = settings.enabledPlatforms ?? ['subito', 'facebook_marketplace', 'vinted'];
    } finally {
      this.loading.set(false);
    }
  }

  async save(): Promise<void> {
    const currentSettings = this.settingsService.settings();
    const settings: AppSettings = {
      catalogRoot: this.catalogRoot,
      aiHost: this.aiHost,
      aiToken: this.aiToken,
      aiModel: this.aiModel,
      language: this.language,
      recentFolders: currentSettings?.recentFolders || [],
      fbEmail: currentSettings?.fbEmail || '',
      fbPassword: currentSettings?.fbPassword || '',
      enabledPlatforms: this.enabledPlatforms,
    };

    try {
      await this.settingsService.save(settings);
      this.snackBar.open('Settings saved', 'OK', { duration: 2000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }

  async browseCatalogRoot(): Promise<void> {
    try {
      const result = await invoke<string[]>('pick_folder');
      if (result.length > 0) {
        const firstFile = result[0];
        const sep = firstFile.includes('\\') ? '\\' : '/';
        const folder = firstFile.substring(0, firstFile.lastIndexOf(sep));
        if (folder) {
          this.catalogRoot = folder;
        }
      }
    } catch {
      // User cancelled
    }
  }

  async openLoginSession(providerId: string): Promise<void> {
    try {
      await invoke('open_provider_session', { providerId });
      this.snackBar.open('Browser opened. Complete login manually, then close or leave it open.', 'OK', { duration: 4000 });
    } catch (err) {
      this.snackBar.open(`Unable to open browser session: ${err}`, 'OK', { duration: 5000 });
    }
  }

  async clearAllAppData(): Promise<void> {
    const confirmed = window.confirm(
      'This will delete ALL app data (catalog copies, publication records, and settings).\\n\\nOriginal source photos will NOT be deleted.\\n\\nContinue?'
    );
    if (!confirmed) return;

    try {
      await invoke('clear_all_app_data');
      const settings = await this.settingsService.load();
      this.catalogRoot = settings.catalogRoot;
      this.aiHost = settings.aiHost;
      this.aiToken = settings.aiToken;
      this.aiModel = settings.aiModel;
      this.language = settings.language;
      this.enabledPlatforms = settings.enabledPlatforms ?? ['subito', 'facebook_marketplace', 'vinted'];
      this.snackBar.open('All app data cleared.', 'OK', { duration: 3000 });
    } catch (err) {
      this.snackBar.open(`Failed to clear app data: ${err}`, 'OK', { duration: 5000 });
    }
  }
}
