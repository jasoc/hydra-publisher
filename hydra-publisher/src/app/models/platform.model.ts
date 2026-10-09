export interface PlatformInfo {
  id: string;
  name: string;
}

export interface PublishRecord {
  articleId: string;
  platformId: string;
  status:
    | 'NotPublished'
    | 'AwaitingLogin'
    | 'Publishing'
    | 'Published'
    | { Failed: string };
}

export interface PublishTarget {
  articleId: string;
  platformId: string;
}
