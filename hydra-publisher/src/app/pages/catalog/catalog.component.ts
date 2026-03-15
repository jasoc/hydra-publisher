import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatBadgeModule } from '@angular/material/badge';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { CatalogService } from '../../services/catalog.service';
import { AiService } from '../../services/ai.service';
import { Article } from '../../models/article.model';
import { convertFileSrc } from '@tauri-apps/api/core';

@Component({
  selector: 'app-catalog',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatBadgeModule,
    MatSnackBarModule,
  ],
  templateUrl: './catalog.component.html',
  styleUrl: './catalog.component.scss',
})
export class CatalogComponent implements OnInit {
  articles = signal<Article[]>([]);
  loading = signal(false);

  constructor(
    private catalogService: CatalogService,
    private aiService: AiService,
    private snackBar: MatSnackBar,
    private router: Router,
  ) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      await this.catalogService.loadArticles();
      this.articles.set(this.catalogService.articles());
    } finally {
      this.loading.set(false);
    }
  }

  getThumbUrl(article: Article): string | null {
    if (article.photos.length === 0) return null;
    return convertFileSrc(`${article.folderPath}/${article.photos[0]}`);
  }

  openArticle(article: Article): void {
    this.router.navigate(['/catalog', encodeURIComponent(article.folderPath)]);
  }

  async askAiFill(): Promise<void> {
    const articles = this.articles();
    const needsFill = articles.filter(
      a =>
        a.name.startsWith('Article ') ||
        !a.description ||
        !a.price ||
        a.price === 0,
    );

    if (needsFill.length === 0) {
      this.snackBar.open('All articles already have complete information', 'OK', {
        duration: 3000,
      });
      return;
    }

    try {
      const ids = needsFill.map(a => a.id);
      await this.aiService.startFill(ids);
      this.snackBar.open(
        `AI processing started for ${needsFill.length} articles`,
        'OK',
        { duration: 3000 },
      );
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }
}
