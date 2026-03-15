import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { PhotoGridComponent } from '../../shared/photo-grid/photo-grid.component';
import { CatalogService } from '../../services/catalog.service';
import { PhotoService } from '../../services/photo.service';
import { Article } from '../../models/article.model';
import { convertFileSrc } from '@tauri-apps/api/core';

@Component({
  selector: 'app-article-detail',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    PhotoGridComponent,
  ],
  templateUrl: './article-detail.component.html',
  styleUrl: './article-detail.component.scss',
})
export class ArticleDetailComponent implements OnInit {
  article = signal<Article | null>(null);
  loading = signal(false);

  // Editable fields
  name = '';
  description = '';
  price: number | null = null;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private catalogService: CatalogService,
    private photoService: PhotoService,
    private snackBar: MatSnackBar,
  ) {}

  async ngOnInit(): Promise<void> {
    const folderPath = decodeURIComponent(this.route.snapshot.params['id']);
    this.loading.set(true);
    try {
      const article = await this.catalogService.getArticle(folderPath);
      this.article.set(article);
      this.name = article.name;
      this.description = article.description;
      this.price = article.price;
    } finally {
      this.loading.set(false);
    }
  }

  getPhotoPaths(): string[] {
    const a = this.article();
    if (!a) return [];
    return a.photos.map(p => `${a.folderPath}/${p}`);
  }

  getVideoUrl(video: string): string {
    const a = this.article();
    if (!a) return '';
    return convertFileSrc(`${a.folderPath}/${video}`);
  }

  async save(): Promise<void> {
    const a = this.article();
    if (!a) return;

    const updated: Article = {
      ...a,
      name: this.name,
      description: this.description,
      price: this.price,
    };

    try {
      const result = await this.catalogService.updateArticle(updated);
      this.article.set(result);
      this.snackBar.open('Article saved', 'OK', { duration: 2000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }

  async addPhotos(): Promise<void> {
    const a = this.article();
    if (!a) return;

    const files = await this.photoService.pickFiles();
    if (files.length === 0) return;

    try {
      const newFilenames = await this.photoService.copyPhotosToArticle(files, a.folderPath);
      const updated: Article = {
        ...a,
        photos: [...a.photos, ...newFilenames],
      };
      const result = await this.catalogService.updateArticle(updated);
      this.article.set(result);
      this.snackBar.open(`Added ${newFilenames.length} photos`, 'OK', { duration: 2000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }

  goBack(): void {
    this.router.navigate(['/catalog']);
  }
}
