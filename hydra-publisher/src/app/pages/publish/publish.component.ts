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
import { SettingsService } from '../../services/settings.service';
import { Article } from '../../models/article.model';
import { PlatformInfo, PublishRecord, PublishTarget } from '../../models/platform.model';
import { invoke } from '@tauri-apps/api/core';

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
    private settingsService: SettingsService,
    private snackBar: MatSnackBar,
  ) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      await Promise.all([
        this.catalogService.loadArticles(),
        this.publishService.loadPlatforms(),
        this.publishService.refreshRecords(),
        this.settingsService.load(),
      ]);
      this.articles.set(this.catalogService.articles());
      const enabledPlatforms = this.settingsService.settings()?.enabledPlatforms ?? ['test', 'facebook_marketplace'];
      this.platforms.set(
        this.publishService.platforms().filter(p => enabledPlatforms.includes(p.id))
      );
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

  isAwaitingLogin(status: any): boolean {
    return status === 'AwaitingLogin';
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
    if (this.isAwaitingLogin(status)) return 'login';
    return 'radio_button_unchecked';
  }

  statusClass(status: any): string {
    if (this.isSuccess(status))    return 'status-success';
    if (this.isError(status))      return 'status-error';
    if (this.isInProgress(status)) return 'status-progress';
    if (this.isAwaitingLogin(status)) return 'status-awaiting';
    return 'status-idle';
  }

  statusLabel(status: any): string {
    if (status === 'Published')  return 'Published';
    if (status === 'Updated')    return 'Updated';
    if (status === 'Publishing') return 'Publishing…';
    if (status === 'Updating')   return 'Updating…';
    if (status === 'AwaitingLogin') return 'Awaiting login';
    if (typeof status === 'object' && 'Failed' in status)
      return `Failed: ${status['Failed']}`;
    if (typeof status === 'object' && 'UpdateFailed' in status)
      return `Failed: ${status['UpdateFailed']}`;
    return String(status);
  }

  groupSummary(group: ArticleGroup): { success: number; error: number; progress: number; awaiting: number } {
    let success = 0, error = 0, progress = 0, awaiting = 0;
    for (const r of group.records) {
      if (this.isSuccess(r.status))    success++;
      else if (this.isError(r.status)) error++;
      else if (this.isInProgress(r.status)) progress++;
      else if (this.isAwaitingLogin(r.status)) awaiting++;
    }
    return { success, error, progress, awaiting };
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
          r =>
            r.articleId === articleId
            && r.platformId === p.id
            && (r.status === 'Published' || r.status === 'Updated')
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

  /** True if this article is already published on this platform. */
  isAlreadyPublished(articleId: string, platformId: string): boolean {
    return this.records().some(
      r =>
        r.articleId === articleId
        && r.platformId === platformId
        && (r.status === 'Published' || r.status === 'Updated')
    );
  }

  toggleMatrix(articleId: string, platformId: string): void {
    const matrix = new Map(this.matrixSelections());
    const ps = new Set<string>(matrix.get(articleId) ?? new Set());
    if (ps.has(platformId)) ps.delete(platformId); else ps.add(platformId);
    matrix.set(articleId, ps);
    this.matrixSelections.set(matrix);
  }

  supportsUpdate(platformId: string): boolean {
    return this.platforms().find(p => p.id === platformId)?.supportsUpdate ?? true;
  }

  matrixSelectAll(): void {
    const matrix = new Map<string, Set<string>>();
    for (const articleId of this.selectedArticleIds()) {
      const ps = new Set<string>();
      for (const p of this.platforms()) {
        ps.add(p.id);
      }
      matrix.set(articleId, ps);
    }
    this.matrixSelections.set(matrix);
  }

  matrixDeselectAll(): void {
    const matrix = new Map<string, Set<string>>();
    for (const articleId of this.selectedArticleIds()) {
      matrix.set(articleId, new Set<string>());
    }
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
    const targets: PublishTarget[] = [];
    for (const [articleId, ps] of matrix) {
      for (const pid of ps) {
        targets.push({ articleId, platformId: pid });
      }
    }
    if (targets.length === 0) {
      this.snackBar.open('No targets selected', 'OK', { duration: 3000 });
      return;
    }

    this.step.set('publishing');
    try {
      await this.publishService.publish(targets);
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

  async forceResetRecord(record: PublishRecord): Promise<void> {
    try {
      await invoke('force_reset_task', {
        articleId: record.articleId,
        platformId: record.platformId,
      });
      await this.publishService.refreshRecords();
      this.records.set(this.publishService.records());
      this.snackBar.open('Task reset to Failed.', 'OK', { duration: 3000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }

  async retryRecord(record: PublishRecord): Promise<void> {
    if (record.platformId === 'ebay') {
      // eBay needs to delete the broken offer first
      const confirmed = window.confirm(
        `Delete the eBay offer for "${this.getArticleName(record.articleId)}" and retry?\n\n` +
        `This will remove the broken offer from eBay and reset the record so you can republish.`
      );
      if (!confirmed) return;

      try {
        const msg = await invoke<string>('delete_ebay_offer', { articleId: record.articleId });
        this.snackBar.open(msg, 'OK', { duration: 4000 });
        await this.publishService.refreshRecords();
        this.records.set(this.publishService.records());
      } catch (err) {
        this.snackBar.open(`Delete failed: ${err}`, 'OK', { duration: 6000 });
        return;
      }

      // Automatically retry publish
      try {
        await this.publishService.publish([{ articleId: record.articleId, platformId: record.platformId }]);
        this.records.set(this.publishService.records());
        this.snackBar.open('Republished successfully!', 'OK', { duration: 3000 });
      } catch (err) {
        this.snackBar.open(`Retry failed: ${err}`, 'OK', { duration: 5000 });
      }
    } else {
      // Non-eBay platforms: reset and republish via backend
      try {
        await invoke('retry_publish', {
          articleId: record.articleId,
          platformId: record.platformId,
        });
        await this.publishService.refreshRecords();
        this.records.set(this.publishService.records());
        this.snackBar.open('Republished successfully!', 'OK', { duration: 3000 });
      } catch (err) {
        this.snackBar.open(`Retry failed: ${err}`, 'OK', { duration: 5000 });
      }
    }
  }
}
