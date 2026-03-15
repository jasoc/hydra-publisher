import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
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
        // Extract folder from the first photo path
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
}
