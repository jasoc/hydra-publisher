export interface AiRequest {
  id: string;
  articleId: string;
  articleName: string;
  description: string;
  status: 'Pending' | 'InProgress' | 'Completed' | { Failed: string };
  photoCount: number;
}
