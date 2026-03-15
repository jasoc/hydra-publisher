import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { CatalogService } from '../../services/catalog.service';
import { PublishService } from '../../services/publish.service';
import { Article } from '../../models/article.model';
import { PlatformInfo, PublishRecord } from '../../models/platform.model';

interface ArticleGroup {
  articleId: string;
  articleName: string;
  records: PublishRecord[];
}

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
    MatTooltipModule,
  ],
  templateUrl: './publish.component.html',
  styleUrl: './publish.component.scss',
})
export class PublishComponent implements OnInit {
  articles = signal<Article[]>([]);
  platforms = signal<PlatformInfo[]>([]);
  records = signal<PublishRecord[]>([]);
  loading = signal(false);
  expandedIds = signal<Set<string>>(new Set());

  step = signal<'idle' | 'select-articles' | 'select-matrix' | 'publishing'>('idle');
  selectedArticleIds = signal<Set<string>>(new Set());
  matrixSelections = signal<Map<string, Set<string>>>(new Map());

  /** Records grouped by article, sorted by name. */
  articleGroups = computed<ArticleGroup[]>(() => {
    const byArticle = new Map<string, PublishRecord[]>();
    for (const r of this.records()) {
      if (!byArticle.has(r.articleId)) byArticle.set(r.articleId, []);
      byArticle.get(r.articleId)!.push(r);
    }
    return Array.from(byArticle.entries())
      .map(([articleId, records]) => ({
        articleId,
        articleName: this.articles().find(a => a.id === articleId)?.name ?? articleId,
        records,
      }))
      .sort((a, b) => a.articleName.localeCompare(b.articleName));
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

  // ---- Expand / collapse ---------------------------------------------------

  toggleExpand(articleId: string): void {
    const s = new Set(this.expandedIds());
    if (s.has(articleId)) s.delete(articleId); else s.add(articleId);
    this.expandedIds.set(s);
  }

  isExpanded(articleId: string): boolean {
    return this.expandedIds().has(articleId);
  }

  // ---- Status helpers ------------------------------------------------------

  isInProgress(status: any): boolean {
    return status === 'Publishing' || status === 'Updating';
  }

  isSuccess(status: any): boolean {
    return status === 'Published' || status === 'Updated';
  }

  isError(status: any): boolean {
    return typeof status === 'object' && ('Failed' in status || 'UpdateFailed' in status);
  }

  getErrorMessage(status: any): string {
    if (typeof status === 'object') return status['Failed'] ?? status['UpdateFailed'] ?? '';
    return '';
  }

  statusIcon(status: any): string {
    if (this.isSuccess(status))    return 'check_circle';
    if (this.isError(status))      return 'error';
    if (this.isInProgress(status)) return 'sync';
    return 'radio_button_unchecked';
  }

  statusClass(status: any): string {
    if (this.isSuccess(status))    return 'status-success';
    if (this.isError(status))      return 'status-error';
    if (this.isInProgress(status)) return 'status-progress';
    return 'status-idle';
  }

  statusLabel(status: any): string {
    if (status === 'Published')  return 'Published';
    if (status === 'Updated')    return 'Updated';
    if (status === 'Publishing') return 'Publishing…';
    if (status === 'Updating')   return 'Updating…';
    if (typeof status === 'object' && 'Failed' in status)
      return `Failed: ${status['Failed']}`;
    if (typeof status === 'object' && 'UpdateFailed' in status)
      return `Failed: ${status['UpdateFailed']}`;
    return String(status);
  }

  groupSummary(group: ArticleGroup): { success: number; error: number; progress: number } {
    let success = 0, error = 0, progress = 0;
    for (const r of group.records) {
      if (this.isSuccess(r.status))    success++;
      else if (this.isError(r.status)) error++;
      else if (this.isInProgress(r.status)) progress++;
    }
    return { success, error, progress };
  }

  // ---- Publish flow --------------------------------------------------------

  startSellFlow(): void {
    this.selectedArticleIds.set(new Set());
    this.matrixSelections.set(new Map());
    this.step.set('select-articles');
  }

  cancelFlow(): void { this.step.set('idle'); }

  toggleArticle(id: string): void {
    const s = new Set(this.selectedArticleIds());
    if (s.has(id)) s.delete(id); else s.add(id);
    this.selectedArticleIds.set(s);
  }

  isArticleSelected(id: string): boolean {
    return this.selectedArticleIds().has(id);
  }

  goToMatrix(): void {
    const matrix = new Map<string, Set<string>>();
    for (const articleId of this.selectedArticleIds()) {
      const ps = new Set<string>();
      for (const p of this.platforms()) {
        const published = this.records().some(
          r => r.articleId === articleId && r.platformId === p.id && r.status === 'Published'
        );
        if (!published) ps.add(p.id);
      }
      matrix.set(articleId, ps);
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
    const ps = new Set<string>(matrix.get(articleId) ?? new Set());
    if (ps.has(platformId)) ps.delete(platformId); else ps.add(platformId);
    matrix.set(articleId, ps);
    this.matrixSelections.set(matrix);
  }

  getArticleName(id: string): string {
    return this.articles().find(a => a.id === id)?.name ?? id;
  }

  getPlatformName(id: string): string {
    return this.platforms().find(p => p.id === id)?.name ?? id;
  }

  async executePublish(): Promise<void> {
    const matrix = this.matrixSelections();
    const articleIds: string[] = [];
    const platformIds = new Set<string>();
    for (const [articleId, ps] of matrix) {
      if (ps.size > 0) {
        articleIds.push(articleId);
        for (const pid of ps) platformIds.add(pid);
      }
    }
    if (articleIds.length === 0) {
      this.snackBar.open('No articles selected', 'OK', { duration: 3000 });
      return;
    }
    this.step.set('publishing');
    try {
      await this.publishService.publish(articleIds, Array.from(platformIds));
      this.records.set(this.publishService.records());
      this.snackBar.open('Publishing complete!', 'OK', { duration: 3000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    } finally {
      this.step.set('idle');
    }
  }

  async syncRecord(record: PublishRecord): Promise<void> {
    try {
      await this.publishService.update([record.articleId], [record.platformId]);
      this.records.set(this.publishService.records());
      this.snackBar.open('Sync complete!', 'OK', { duration: 2000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }
}
