import { Component, OnInit, OnDestroy, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { invoke } from '@tauri-apps/api/core';
import { PublishRecord } from '../../models/platform.model';
import { PublishService } from '../../services/publish.service';
import { CatalogService } from '../../services/catalog.service';

@Component({
  selector: 'app-tasks',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
    MatDividerModule,
  ],
  templateUrl: './tasks.component.html',
  styleUrl: './tasks.component.scss',
})
export class TasksComponent implements OnInit, OnDestroy {
  records = signal<PublishRecord[]>([]);
  activeSessions = signal<string[]>([]);
  loading = signal(false);

  private pollInterval: ReturnType<typeof setInterval> | null = null;

  inProgressRecords = computed(() =>
    this.records().filter(r => this.isInProgress(r.status) || r.status === 'AwaitingLogin')
  );

  successRecords = computed(() =>
    this.records().filter(r => this.isSuccess(r.status))
  );

  failedRecords = computed(() =>
    this.records().filter(r => this.isError(r.status))
  );

  constructor(
    private publishService: PublishService,
    private catalogService: CatalogService,
    private snackBar: MatSnackBar,
  ) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      await Promise.all([
        this.catalogService.loadArticles(),
        this.publishService.refreshRecords(),
      ]);
      this.records.set(this.publishService.records());
      await this.refreshSessions();
    } finally {
      this.loading.set(false);
    }

    // Auto-refresh while there are in-progress tasks
    this.pollInterval = setInterval(() => this.poll(), 3000);
  }

  ngOnDestroy(): void {
    if (this.pollInterval !== null) {
      clearInterval(this.pollInterval);
    }
  }

  private async poll(): Promise<void> {
    if (this.inProgressRecords().length > 0) {
      await this.publishService.refreshRecords();
      this.records.set(this.publishService.records());
    }
    await this.refreshSessions();
  }

  private async refreshSessions(): Promise<void> {
    try {
      const sessions = await invoke<string[]>('get_active_sessions');
      this.activeSessions.set(sessions);
    } catch {
      // Python bridge not started yet — no sessions
      this.activeSessions.set([]);
    }
  }

  async forceReset(record: PublishRecord): Promise<void> {
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

  async killSession(providerId: string): Promise<void> {
    try {
      await invoke('kill_session', { providerId });
      await this.refreshSessions();
      this.snackBar.open(`Session "${providerId}" closed.`, 'OK', { duration: 3000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }

  async refresh(): Promise<void> {
    this.loading.set(true);
    try {
      await this.publishService.refreshRecords();
      this.records.set(this.publishService.records());
      await this.refreshSessions();
    } finally {
      this.loading.set(false);
    }
  }

  getArticleName(id: string): string {
    return this.catalogService.articles().find(a => a.id === id)?.name ?? id;
  }

  isInProgress(status: any): boolean {
    return status === 'Publishing' || status === 'Updating';
  }

  isSuccess(status: any): boolean {
    return status === 'Published' || status === 'Updated';
  }

  isError(status: any): boolean {
    return typeof status === 'object' && ('Failed' in status || 'UpdateFailed' in status);
  }

  statusIcon(status: any): string {
    if (this.isSuccess(status))    return 'check_circle';
    if (this.isError(status))      return 'error';
    if (status === 'Publishing' || status === 'Updating') return 'sync';
    if (status === 'AwaitingLogin') return 'login';
    return 'radio_button_unchecked';
  }

  statusClass(status: any): string {
    if (this.isSuccess(status))    return 'status-success';
    if (this.isError(status))      return 'status-error';
    if (this.isInProgress(status)) return 'status-progress';
    if (status === 'AwaitingLogin') return 'status-awaiting';
    return 'status-idle';
  }

  statusLabel(status: any): string {
    if (status === 'Published')     return 'Published';
    if (status === 'Updated')       return 'Updated';
    if (status === 'Publishing')    return 'Publishing…';
    if (status === 'Updating')      return 'Updating…';
    if (status === 'AwaitingLogin') return 'Awaiting login';
    if (typeof status === 'object' && 'Failed' in status)
      return `Failed: ${status['Failed']}`;
    if (typeof status === 'object' && 'UpdateFailed' in status)
      return `Failed: ${status['UpdateFailed']}`;
    return String(status);
  }
}
