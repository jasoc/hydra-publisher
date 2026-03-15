import { Component, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { PhotoGridComponent } from '../../shared/photo-grid/photo-grid.component';
import { PhotoService } from '../../services/photo.service';
import { CatalogService } from '../../services/catalog.service';
import { SettingsService } from '../../services/settings.service';

@Component({
  selector: 'app-import',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatSnackBarModule,
    PhotoGridComponent,
  ],
  templateUrl: './import.component.html',
  styleUrl: './import.component.scss',
})
export class ImportComponent implements OnInit {
  photos = signal<string[]>([]);
  selectedPhotos = signal<string[]>([]);
  recentFolders = signal<string[]>([]);
  loading = signal(false);

  constructor(
    private photoService: PhotoService,
    private catalogService: CatalogService,
    private settingsService: SettingsService,
    private snackBar: MatSnackBar,
  ) {}

  async ngOnInit(): Promise<void> {
    const settings = await this.settingsService.load();
    this.recentFolders.set(settings.recentFolders || []);
  }

  async pickFolder(): Promise<void> {
    this.loading.set(true);
    try {
      const photos = await this.photoService.pickFolder();
      if (photos.length > 0) {
        this.photos.set(photos);
        this.selectedPhotos.set([]);

        // Save folder to recent
        const folderPath = photos[0].substring(0, photos[0].lastIndexOf('/')) ||
                           photos[0].substring(0, photos[0].lastIndexOf('\\'));
        if (folderPath) {
          await this.addRecentFolder(folderPath);
        }
      }
    } finally {
      this.loading.set(false);
    }
  }

  async loadFromRecent(folder: string): Promise<void> {
    this.loading.set(true);
    try {
      const photos = await this.photoService.listPhotosInFolder(folder);
      this.photos.set(photos);
      this.selectedPhotos.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  onSelectionChange(selected: string[]): void {
    this.selectedPhotos.set(selected);
  }

  async createArticle(): Promise<void> {
    const selected = this.selectedPhotos();
    if (selected.length === 0) return;

    this.loading.set(true);
    try {
      const article = await this.catalogService.createArticle(null, selected);
      this.snackBar.open(`Created "${article.name}" with ${selected.length} photos`, 'OK', {
        duration: 3000,
      });

      // Remove created photos from the grid
      const remaining = this.photos().filter(p => !selected.includes(p));
      this.photos.set(remaining);
      this.selectedPhotos.set([]);
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    } finally {
      this.loading.set(false);
    }
  }

  private async addRecentFolder(folder: string): Promise<void> {
    const settings = await this.settingsService.load();
    const recent = [folder, ...(settings.recentFolders || []).filter(f => f !== folder)].slice(0, 5);
    settings.recentFolders = recent;
    await this.settingsService.save(settings);
    this.recentFolders.set(recent);
  }

  getFolderName(path: string): string {
    const sep = path.includes('\\') ? '\\' : '/';
    const parts = path.split(sep);
    return parts[parts.length - 1] || path;
  }
}
