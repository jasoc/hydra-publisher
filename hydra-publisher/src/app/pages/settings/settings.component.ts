import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { SettingsService } from '../../services/settings.service';
import { AppSettings } from '../../models/settings.model';
import { invoke } from '@tauri-apps/api/core';
import { openUrl } from '@tauri-apps/plugin-opener';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
  ],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss',
})
export class SettingsComponent implements OnInit {
  loading = signal(false);

  catalogRoot = '';
  aiHost = '';
  aiToken = '';
  aiModel = '';
  language = '';
  ebayToken = '';
  ebayMarketplaceId = 'EBAY_IT';
  ebayFulfillmentPolicyId = '';
  ebayPaymentPolicyId = '';
  ebayReturnPolicyId = '';
  ebayCategoryId = '';
  categorySearchQuery = '';
  categorySearchResults: { categoryId: string; categoryName: string; categoryPath: string }[] = [];
  searchingCategories = signal(false);

  async searchEbayCategories(): Promise<void> {
    if (!this.ebayToken || !this.categorySearchQuery.trim()) return;
    this.searchingCategories.set(true);
    this.categorySearchResults = [];
    try {
      this.categorySearchResults = await invoke<{ categoryId: string; categoryName: string; categoryPath: string }[]>(
        'search_ebay_categories',
        { token: this.ebayToken, marketplaceId: this.ebayMarketplaceId, query: this.categorySearchQuery }
      );
      if (this.categorySearchResults.length === 0) {
        this.snackBar.open('No categories found', 'OK', { duration: 2000 });
      }
    } catch (err) {
      this.snackBar.open(`Category search failed: ${err}`, 'OK', { duration: 5000 });
    } finally {
      this.searchingCategories.set(false);
    }
  }

  selectCategory(cat: { categoryId: string; categoryPath: string }): void {
    this.ebayCategoryId = cat.categoryId;
    this.categorySearchResults = [];
    this.categorySearchQuery = '';
    this.snackBar.open(`Category set: ${cat.categoryPath} (${cat.categoryId})`, 'OK', { duration: 3000 });
  }

  ebayMarketplaces = [
    { value: 'EBAY_IT', label: 'Italy (EBAY_IT)' },
    { value: 'EBAY_DE', label: 'Germany (EBAY_DE)' },
    { value: 'EBAY_FR', label: 'France (EBAY_FR)' },
    { value: 'EBAY_ES', label: 'Spain (EBAY_ES)' },
    { value: 'EBAY_UK', label: 'United Kingdom (EBAY_UK)' },
    { value: 'EBAY_US', label: 'United States (EBAY_US)' },
  ];

  languages = [
    { value: 'en', label: 'English' },
    { value: 'it', label: 'Italian' },
    { value: 'fr', label: 'French' },
    { value: 'de', label: 'German' },
    { value: 'es', label: 'Spanish' },
    { value: 'pt', label: 'Portuguese' },
  ];

  constructor(
    private settingsService: SettingsService,
    private snackBar: MatSnackBar,
  ) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      const settings = await this.settingsService.load();
      this.catalogRoot = settings.catalogRoot;
      this.aiHost = settings.aiHost;
      this.aiToken = settings.aiToken;
      this.aiModel = settings.aiModel;
      this.language = settings.language;
      this.ebayToken = settings.ebayToken || '';
      this.ebayMarketplaceId = settings.ebayMarketplaceId || 'EBAY_IT';
      this.ebayFulfillmentPolicyId = settings.ebayFulfillmentPolicyId || '';
      this.ebayPaymentPolicyId = settings.ebayPaymentPolicyId || '';
      this.ebayReturnPolicyId = settings.ebayReturnPolicyId || '';
      this.ebayCategoryId = settings.ebayCategoryId || '';
    } finally {
      this.loading.set(false);
    }
  }

  loadingPolicies = signal(false);

  async fetchEbayPolicies(): Promise<void> {
    if (!this.ebayToken) {
      this.snackBar.open('Enter the eBay token first', 'OK', { duration: 3000 });
      return;
    }
    this.loadingPolicies.set(true);
    try {
      const policies = await invoke<{
        fulfillmentPolicyId: string;
        fulfillmentPolicyName: string;
        paymentPolicyId: string;
        paymentPolicyName: string;
        returnPolicyId: string;
        returnPolicyName: string;
      }>('fetch_ebay_policies', {
        token: this.ebayToken,
        marketplaceId: this.ebayMarketplaceId,
      });
      this.ebayFulfillmentPolicyId = policies.fulfillmentPolicyId;
      this.ebayPaymentPolicyId = policies.paymentPolicyId;
      this.ebayReturnPolicyId = policies.returnPolicyId;
      this.snackBar.open(
        `Loaded: ${policies.fulfillmentPolicyName} / ${policies.paymentPolicyName} / ${policies.returnPolicyName}`,
        'OK',
        { duration: 4000 }
      );
    } catch (err) {
      const errStr = String(err);
      if (errStr.startsWith('BUSINESS_POLICY_NOT_ENABLED:')) {
        const url = errStr.split(':').slice(1).join(':');
        const ref = this.snackBar.open(
          'eBay Business Policies not enabled on your account.',
          'Enable now',
          { duration: 10000 }
        );
        ref.onAction().subscribe(() => openUrl(url));
      } else {
        this.snackBar.open(`Failed to fetch policies: ${errStr}`, 'OK', { duration: 5000 });
      }
    } finally {
      this.loadingPolicies.set(false);
    }
  }

  async save(): Promise<void> {
    const currentSettings = this.settingsService.settings();
    const settings: AppSettings = {
      catalogRoot: this.catalogRoot,
      aiHost: this.aiHost,
      aiToken: this.aiToken,
      aiModel: this.aiModel,
      language: this.language,
      recentFolders: currentSettings?.recentFolders || [],
      ebayToken: this.ebayToken,
      ebayMarketplaceId: this.ebayMarketplaceId,
      ebayFulfillmentPolicyId: this.ebayFulfillmentPolicyId,
      ebayPaymentPolicyId: this.ebayPaymentPolicyId,
      ebayReturnPolicyId: this.ebayReturnPolicyId,
      ebayCategoryId: this.ebayCategoryId,
    };

    try {
      await this.settingsService.save(settings);
      this.snackBar.open('Settings saved', 'OK', { duration: 2000 });
    } catch (err) {
      this.snackBar.open(`Error: ${err}`, 'OK', { duration: 5000 });
    }
  }

  async browseCatalogRoot(): Promise<void> {
    try {
      const result = await invoke<string[]>('pick_folder');
      if (result.length > 0) {
        // Extract folder from the first photo path
        const firstFile = result[0];
        const sep = firstFile.includes('\\') ? '\\' : '/';
        const folder = firstFile.substring(0, firstFile.lastIndexOf(sep));
        if (folder) {
          this.catalogRoot = folder;
        }
      }
    } catch {
      // User cancelled
    }
  }
}
