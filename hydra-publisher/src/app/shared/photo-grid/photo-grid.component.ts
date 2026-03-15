import { Component, input, output, signal, computed, effect, untracked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { convertFileSrc } from '@tauri-apps/api/core';

@Component({
  selector: 'app-photo-grid',
  standalone: true,
  imports: [CommonModule, MatCheckboxModule],
  templateUrl: './photo-grid.component.html',
  styleUrl: './photo-grid.component.scss',
})
export class PhotoGridComponent {
  photoPaths = input.required<string[]>();
  selectable = input<boolean>(true);
  selectedChange = output<string[]>();

  private selectedSet = signal<Set<string>>(new Set());

  constructor() {
    effect(() => {
      const paths = new Set(this.photoPaths());
      const current = untracked(() => this.selectedSet());
      const cleaned = new Set([...current].filter(p => paths.has(p)));
      if (cleaned.size !== current.size) {
        this.selectedSet.set(cleaned);
        this.selectedChange.emit(Array.from(cleaned));
      }
    });
  }

  selected = computed(() => Array.from(this.selectedSet()));

  getPhotoUrl(path: string): string {
    return convertFileSrc(path);
  }

  isSelected(path: string): boolean {
    return this.selectedSet().has(path);
  }

  togglePhoto(path: string): void {
    if (!this.selectable()) return;
    const current = new Set(this.selectedSet());
    if (current.has(path)) {
      current.delete(path);
    } else {
      current.add(path);
    }
    this.selectedSet.set(current);
    this.selectedChange.emit(Array.from(current));
  }

  selectAll(): void {
    const all = new Set(this.photoPaths());
    this.selectedSet.set(all);
    this.selectedChange.emit(Array.from(all));
  }

  deselectAll(): void {
    this.selectedSet.set(new Set());
    this.selectedChange.emit([]);
  }

  isVideo(path: string): boolean {
    const ext = path.split('.').pop()?.toLowerCase() || '';
    return ['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext);
  }
}
