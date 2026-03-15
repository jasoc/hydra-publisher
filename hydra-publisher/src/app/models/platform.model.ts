export interface PlatformInfo {
  id: string;
  name: string;
}

export interface PublishRecord {
  articleId: string;
  platformId: string;
  status: 'NotPublished' | 'Publishing' | 'Published' | { Failed: string };
}
