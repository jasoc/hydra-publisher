import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { AiService } from '../../services/ai.service';
import { AiRequest } from '../../models/ai-request.model';

@Component({
  selector: 'app-ai-requests',
  standalone: true,
  imports: [
    CommonModule,
    MatListModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatButtonModule,
  ],
  templateUrl: './ai-requests.component.html',
  styleUrl: './ai-requests.component.scss',
})
export class AiRequestsComponent implements OnInit, OnDestroy {
  requests = signal<AiRequest[]>([]);
  expandedIds = signal<Set<string>>(new Set());

  constructor(private aiService: AiService) {}

  async ngOnInit(): Promise<void> {
    this.aiService.startPolling();
    await this.aiService.refreshRequests();
    this.requests.set(this.aiService.requests());

    // Keep updating the signal from service
    this.pollUpdate();
  }

  ngOnDestroy(): void {
    // Don't stop polling globally - just stop our local update
  }

  private pollUpdate(): void {
    const interval = setInterval(() => {
      this.requests.set(this.aiService.requests());
    }, 1000);

    // Store for future cleanup
    (this as any)._interval = interval;
  }

  getStatusIcon(request: AiRequest): string {
    if (request.status === 'Pending') return 'schedule';
    if (request.status === 'InProgress') return 'sync';
    if (request.status === 'Completed') return 'check_circle';
    return 'error';
  }

  getStatusClass(request: AiRequest): string {
    if (request.status === 'Completed') return 'status-done';
    if (request.status === 'Pending' || request.status === 'InProgress') return 'status-active';
    return 'status-error';
  }

  isActive(request: AiRequest): boolean {
    return request.status === 'Pending' || request.status === 'InProgress';
  }

  getErrorMessage(request: AiRequest): string {
    if (typeof request.status === 'object' && 'Failed' in request.status) {
      return request.status.Failed;
    }
    return '';
  }

  toggleExpanded(id: string): void {
    const current = new Set(this.expandedIds());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.expandedIds.set(current);
  }

  isExpanded(id: string): boolean {
    return this.expandedIds().has(id);
  }
}
