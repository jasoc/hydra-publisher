import { Routes } from "@angular/router";

export const routes: Routes = [
  { path: '', redirectTo: 'import', pathMatch: 'full' },
  {
    path: 'import',
    loadComponent: () => import('./pages/import/import.component').then(m => m.ImportComponent),
  },
  {
    path: 'catalog',
    loadComponent: () => import('./pages/catalog/catalog.component').then(m => m.CatalogComponent),
  },
  {
    path: 'catalog/:id',
    loadComponent: () => import('./pages/article-detail/article-detail.component').then(m => m.ArticleDetailComponent),
  },
  {
    path: 'publish',
    loadComponent: () => import('./pages/publish/publish.component').then(m => m.PublishComponent),
  },
  {
    path: 'ai',
    loadComponent: () => import('./pages/ai-requests/ai-requests.component').then(m => m.AiRequestsComponent),
  },
  {
    path: 'settings',
    loadComponent: () => import('./pages/settings/settings.component').then(m => m.SettingsComponent),
  },
];
