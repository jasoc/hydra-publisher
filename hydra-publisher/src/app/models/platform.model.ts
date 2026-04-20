export interface PlatformInfo {
  id: string;
  name: string;
  supportsUpdate: boolean;
}

export interface PublishRecord {
  articleId: string;
  platformId: string;
  status:
    | 'NotPublished'
    | 'AwaitingLogin'
    | 'Publishing'
    | 'Published'
    | 'Updating'
    | 'Updated'
    | { Failed: string }
    | { UpdateFailed: string };
}

export interface PublishTarget {
  articleId: string;
  platformId: string;
}
