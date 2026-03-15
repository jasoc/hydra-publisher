import { Injectable, signal } from '@angular/core';
import { invoke } from '@tauri-apps/api/core';
import { PlatformInfo, PublishRecord } from '../models/platform.model';

@Injectable({ providedIn: 'root' })
export class PublishService {
  private recordsSignal = signal<PublishRecord[]>([]);
  private platformsSignal = signal<PlatformInfo[]>([]);
  readonly records = this.recordsSignal.asReadonly();
  readonly platforms = this.platformsSignal.asReadonly();

  async loadPlatforms(): Promise<void> {
    const platforms = await invoke<PlatformInfo[]>('list_platforms');
    this.platformsSignal.set(platforms);
  }

  async publish(articleIds: string[], platformIds: string[]): Promise<void> {
    await invoke('publish_articles', { articleIds, platformIds });
    await this.refreshRecords();
  }

  async refreshRecords(): Promise<void> {
    const records = await invoke<PublishRecord[]>('get_publish_records');
    this.recordsSignal.set(records);
  }
}
