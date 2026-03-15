import { Injectable, signal, OnDestroy } from '@angular/core';
import { invoke } from '@tauri-apps/api/core';
import { AiRequest } from '../models/ai-request.model';

@Injectable({ providedIn: 'root' })
export class AiService implements OnDestroy {
  private requestsSignal = signal<AiRequest[]>([]);
  readonly requests = this.requestsSignal.asReadonly();
  private pollInterval: ReturnType<typeof setInterval> | null = null;

  async startFill(articleIds: string[]): Promise<string[]> {
    const ids = await invoke<string[]>('start_ai_fill', { articleIds });
    this.startPolling();
    return ids;
  }

  async refreshRequests(): Promise<void> {
    const requests = await invoke<AiRequest[]>('get_ai_requests');
    this.requestsSignal.set(requests);

    // Stop polling if no active requests
    const hasActive = requests.some(
      r => r.status === 'Pending' || r.status === 'InProgress'
    );
    if (!hasActive && this.pollInterval) {
      this.stopPolling();
    }
  }

  startPolling(): void {
    if (this.pollInterval) return;
    this.pollInterval = setInterval(() => this.refreshRequests(), 2000);
    this.refreshRequests();
  }

  stopPolling(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }
}
