import { Injectable, signal } from '@angular/core';
import { invoke } from '@tauri-apps/api/core';
import { Article } from '../models/article.model';

@Injectable({ providedIn: 'root' })
export class CatalogService {
  private articlesSignal = signal<Article[]>([]);
  readonly articles = this.articlesSignal.asReadonly();

  async loadArticles(): Promise<void> {
    const articles = await invoke<Article[]>('list_articles');
    this.articlesSignal.set(articles);
  }

  async createArticle(name: string | null, photoPaths: string[]): Promise<Article> {
    const article = await invoke<Article>('create_article', { name, photoPaths });
    await this.loadArticles();
    return article;
  }

  async getArticle(folderPath: string): Promise<Article> {
    return invoke<Article>('get_article', { folderPath });
  }

  async updateArticle(article: Article): Promise<Article> {
    const updated = await invoke<Article>('update_article', { article });
    await this.loadArticles();
    return updated;
  }

  async deleteArticle(folderPath: string): Promise<void> {
    await invoke('delete_article', { folderPath });
    await this.loadArticles();
  }
}
