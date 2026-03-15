import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatStepperModule } from '@angular/material/stepper';
import { CatalogService } from '../../services/catalog.service';
import { PublishService } from '../../services/publish.service';
import { Article } from '../../models/article.model';
import { PlatformInfo, PublishRecord } from '../../models/platform.model';

@Component({
  selector: 'app-publish',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatStepperModule,
  ],
  templateUrl: './publish.component.html',
  styleUrl: './publish.component.scss',
})
export class PublishComponent implements OnInit {
  articles = signal<Article[]>([]);
  platforms = signal<PlatformInfo[]>([]);
  records = signal<PublishRecord[]>([]);
  loading = signal(false);

  // Publish flow state
  step = signal<'idle' | 'select-articles' | 'select-matrix' | 'publishing'>('idle');
  selectedArticleIds = signal<Set<string>>(new Set());
  matrixSelections = signal<Map<string, Set<string>>>(new Map()); // articleId -> Set<platformId>

  publishedArticles = computed(() => {
    const recs = this.records();
    return recs.filter(r => r.status === 'Published');
  });

  publishingArticles = computed(() => {
    const recs = this.records();
    return recs.filter(r => r.status === 'Publishing');
  });

  constructor(
    private catalogService: CatalogService,
    private publishService: PublishService,
    private snackBar: MatSnackBar,
  ) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      await Promise.all([
        this.catalogService.loadArticles(),
        this.publishService.loadPlatforms(),
        this.publishService.refreshRecords(),
      ]);
      this.articles.set(this.catalogService.articles());
      this.platforms.set(this.publishService.platforms());
      this.records.set(this.publishService.records());
    } finally {
      this.loading.set(false);
    }
  }

  startSellFlow(): void {
    this.selectedArticleIds.set(new Set());
    this.matrixSelections.set(new Map());
    this.step.set('select-articles');
  }

  cancelFlow(): void {
    this.step.set('idle');
  }

  toggleArticle(id: string): void {
    const current = new Set(this.selectedArticleIds());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.selectedArticleIds.set(current);
  }

  isArticleSelected(id: string): boolean {
    return this.selectedArticleIds().has(id);
  }

  goToMatrix(): void {
    // Initialize matrix: for each selected article, all platforms checked by default
    const matrix = new Map<string, Set<string>>();
    for (const articleId of this.selectedArticleIds()) {
      const platformSet = new Set<string>();
      for (const p of this.platforms()) {
        // Check if already published
        const alreadyPublished = this.records().some(
          r => r.articleId === articleId && r.platformId === p.id && r.status === 'Published'
        );
        if (!alreadyPublished) {
          platformSet.add(p.id);
        }
      }
      matrix.set(articleId, platformSet);
    }
    this.matrixSelections.set(matrix);
    this.step.set('select-matrix');
  }

  isMatrixChecked(articleId: string, platformId: string): boolean {
    return this.matrixSelections().get(articleId)?.has(platformId) || false;
  }

  isMatrixDisabled(articleId: string, platformId: string): boolean {
    return this.records().some(
      r => r.articleId === articleId && r.platformId === platformId && r.status === 'Published'
    );
  }

  toggleMatrix(articleId: string, platformId: string): void {
    if (this.isMatrixDisabled(articleId, platformId)) return;
    const matrix = new Map(this.matrixSelections());
    const platforms = new Set<string>(matrix.get(articleId) || new Set());
    if (platforms.has(platformId)) {
      platforms.delete(platformId);
    } else {
      platforms.add(platformId);
    }
    matrix.set(articleId, platforms);
    this.matrixSelections.set(matrix);
  }

  getArticleName(id: string): string {
    return this.articles().find(a => a.id === id)?.name || id;
  }

  async executePublish(): Promise<void> {
    const matrix = this.matrixSelections();
    const articleIds: string[] = [];
    const platformIds = new Set<string>();

    for (const [articleId, platforms] of matrix) {
      if (platforms.size > 0) {
        articleIds.push(articleId);
        for (const pid of platforms) {
          platformIds.add(pid);
        }
      }
    }

    if (articleIds.length === 0) {
      this.snackBar.open('No articles selected for publishing', 'OK', { duration: 3000 });
      return;
    }

    this.step.set('publishing');
    try {
      await this.publishService.publish(articleIds, Array.from(platformIds));
      this.records.set(this.publishService.records());
      this.snackBar.open('Publishing complete!', 'OK', { duration: 3000 });
      this.step.set('idle');
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
      this.step.set('idle');
    }
  }
}
