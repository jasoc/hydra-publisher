export interface Article {
  id: string;
  name: string;
  description: string;
  price: number | null;
  photos: string[];
  videos: string[];
  folderPath: string;
}
