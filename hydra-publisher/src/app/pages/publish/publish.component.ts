import { Component, OnInit, OnDestroy, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatBadgeModule } from '@angular/material/badge';
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
    MatBadgeModule,
  ],
  templateUrl: './publish.component.html',
  styleUrl: './publish.component.scss',
})
export class PublishComponent implements OnInit, OnDestroy {
  articles = signal<Article[]>([]);
  platforms = signal<PlatformInfo[]>([]);
  records = signal<PublishRecord[]>([]);
  loading = signal(false);
  expandedIds = signal<Set<string>>(new Set());

  step = signal<'idle' | 'select-articles' | 'select-matrix' | 'publishing'>('idle');
  selectedArticleIds = signal<Set<string>>(new Set());
  matrixSelections = signal<Map<string, Set<string>>>(new Map());

  // Chrome pool monitor
  poolSize = signal(0);
  activeSlots = signal<string[]>([]);
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  // Error detail dialog
  errorDialogVisible = signal(false);
  errorDialogTitle = signal('');
  errorDialogMessage = signal('');

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

  ngOnDestroy(): void {
    this.stopPolling();
  }

  // ---- Chrome pool monitor -------------------------------------------------

  private startPolling(): void {
    if (this.pollTimer) return;
    this.pollSessions();
    this.pollTimer = setInterval(() => {
      this.pollSessions();
      this.pollRecords();
    }, 3000);
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private async pollSessions(): Promise<void> {
    try {
      const sessions = await invoke<{ sessions: string[]; poolSize: number }>('get_active_sessions');
      // get_active_sessions returns Vec<String>, but the server now returns
      // { sessions, poolSize } — the Rust bridge only passes Vec<String> though.
      // We'll just use the length here.
      if (Array.isArray(sessions)) {
        this.activeSlots.set(sessions);
      }
    } catch { /* ignore */ }
  }

  private async pollRecords(): Promise<void> {
    try {
      await this.publishService.refreshRecords();
      this.records.set(this.publishService.records());
    } catch { /* ignore */ }
  }

  async killAllSessions(): Promise<void> {
    try {
      await invoke('kill_session', { providerId: 'shared' });
      this.activeSlots.set([]);
      this.snackBar.open('Chrome sessions killed', 'OK', { duration: 2000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }

  // ---- Error dialog --------------------------------------------------------

  showError(articleName: string, status: any): void {
    this.errorDialogTitle.set(`Error — ${articleName}`);
    this.errorDialogMessage.set(this.getErrorMessage(status));
    this.errorDialogVisible.set(true);
  }

  closeErrorDialog(): void {
    this.errorDialogVisible.set(false);
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
    return status === 'Publishing';
  }

  isAwaitingLogin(status: any): boolean {
    return status === 'AwaitingLogin';
  }

  isSuccess(status: any): boolean {
    return status === 'Published';
  }

  isError(status: any): boolean {
    return typeof status === 'object' && 'Failed' in status;
  }

  getErrorMessage(status: any): string {
    if (typeof status === 'object') return status['Failed'] ?? '';
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
    if (status === 'Publishing') return 'Publishing…';
    if (status === 'AwaitingLogin') return 'Awaiting login';
    if (typeof status === 'object' && 'Failed' in status)
      return `Failed: ${status['Failed']}`;
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
            && r.status === 'Published'
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
        && r.status === 'Published'
    );
  }

  toggleMatrix(articleId: string, platformId: string): void {
    const matrix = new Map(this.matrixSelections());
    const ps = new Set<string>(matrix.get(articleId) ?? new Set());
    if (ps.has(platformId)) ps.delete(platformId); else ps.add(platformId);
    matrix.set(articleId, ps);
    this.matrixSelections.set(matrix);
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
    this.startPolling();
    try {
      await this.publishService.publish(targets);
      this.records.set(this.publishService.records());
      this.snackBar.open('Publishing complete!', 'OK', { duration: 3000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    } finally {
      this.stopPolling();
      this.step.set('idle');
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
