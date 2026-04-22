/**
 * Unified product categories for Hydra Publisher.
 *
 * Every category listed here can be selected in the article editor and is
 * mapped by each provider to the platform-specific equivalent.
 *
 * Rules:
 * - Add new categories here ONLY — they propagate automatically to the UI and
 *   to every provider mapping.
 * - Keep labels in Italian, Title Case.
 * - Group labels are for UI display only (mat-optgroup); the stored value is
 *   the individual category string.
 */

export interface CategoryGroup {
  label: string;
  categories: string[];
}

/** Grouped categories for mat-select optgroup display. */
export const CATEGORY_GROUPS: CategoryGroup[] = [
  {
    label: 'Abbigliamento donna',
    categories: [
      'Vestiti donna',
      'Giacche e cappotti donna',
      'Maglioni e pullover donna',
      'Abiti donna',
      'Gonne',
      'Top e t-shirt donna',
      'Jeans donna',
      'Pantaloni donna',
      'Pantaloncini donna',
      'Costumi da bagno donna',
      'Lingerie e pigiami',
      'Abbigliamento sportivo donna',
    ],
  },
  {
    label: 'Scarpe donna',
    categories: [
      'Scarpe donna',
      'Stivali donna',
      'Sandali donna',
      'Tacchi',
      'Sneakers donna',
    ],
  },
  {
    label: 'Borse e accessori donna',
    categories: [
      'Borse',
      'Zaini donna',
      'Pochette',
      'Portafogli donna',
      'Cinture donna',
      'Cappelli donna',
      'Gioielli donna',
      'Sciarpe e scialli donna',
      'Occhiali da sole donna',
      'Orologi donna',
    ],
  },
  {
    label: 'Bellezza',
    categories: [
      'Make-up',
      'Profumi',
      'Cura del viso',
      'Cura del corpo',
    ],
  },
  {
    label: 'Abbigliamento uomo',
    categories: [
      'Vestiti uomo',
      'Giacche e cappotti uomo',
      'Camicie uomo',
      'T-shirt uomo',
      'Maglioni e pullover uomo',
      'Completi e blazer uomo',
      'Pantaloni uomo',
      'Jeans uomo',
      'Pantaloncini uomo',
      'Costumi da bagno uomo',
      'Abbigliamento sportivo uomo',
    ],
  },
  {
    label: 'Scarpe uomo',
    categories: [
      'Scarpe uomo',
      'Stivali uomo',
      'Sneakers uomo',
      'Scarpe formali',
    ],
  },
  {
    label: 'Accessori uomo',
    categories: [
      'Cinture uomo',
      'Cappelli uomo',
      'Gioielli uomo',
      'Cravatte e papillon',
      'Orologi uomo',
      'Occhiali da sole uomo',
    ],
  },
  {
    label: 'Bambini',
    categories: [
      'Abbigliamento bambina',
      'Abbigliamento bambino',
      'Scarpe bambini',
      'Giocattoli',
      'Peluche',
      'Costruzioni',
      'Bambole',
      'Passeggini e carrozzine',
      'Seggiolini auto',
      'Arredamento bambini',
    ],
  },
  {
    label: 'Casa e cucina',
    categories: [
      'Arredamento',
      'Elettrodomestici cucina',
      'Pentole e padelle',
      'Utensili cucina',
      'Stoviglie',
      'Biancheria letto',
      'Tende e tapparelle',
      'Tappeti',
      'Candele e profumi casa',
      'Illuminazione',
      'Cornici',
      'Specchi',
      'Vasi',
      'Decorazioni parete',
    ],
  },
  {
    label: 'Ufficio e casa',
    categories: [
      'Materiale ufficio',
      'Attrezzi e bricolage',
      'Giardino',
      'Animali',
    ],
  },
  {
    label: 'Elettronica',
    categories: [
      'Videogiochi e console',
      'Console',
      'Computer portatili',
      'Computer desktop',
      'Componenti PC',
      'Tastiere',
      'Mouse',
      'Monitor',
      'Stampanti',
      'Smartphone',
      'Accessori telefono',
      'Cuffie e auricolari',
      'Altoparlanti e speaker',
      'Audio e hi-fi',
      'Fotocamere',
      'Obiettivi',
      'Tablet',
      'E-reader',
      'Televisori',
      'Proiettori',
      'Smartwatch',
      'Fitness tracker',
      'Caricabatterie e power bank',
      'Cavi e adattatori',
    ],
  },
  {
    label: 'Intrattenimento',
    categories: [
      'Libri',
      'Narrativa',
      'Saggistica',
      'Fumetti e manga',
      'Riviste',
      'Musica',
      'Vinile',
      'CD',
      'DVD e Blu-ray',
    ],
  },
  {
    label: 'Hobby e collezionismo',
    categories: [
      'Carte collezionabili',
      'Giochi da tavolo',
      'Puzzle',
      'Monete e banconote',
      'Francobolli',
      'Strumenti musicali',
      'Chitarre',
      'Arte e artigianato',
    ],
  },
  {
    label: 'Sport',
    categories: [
      'Ciclismo',
      'Fitness e palestra',
      'Corsa',
      'Yoga e pilates',
      'Campeggio',
      'Arrampicata',
      'Pesca',
      'Nuoto',
      'Surf e SUP',
      'Calcio',
      'Basket',
      'Pallavolo',
      'Tennis',
      'Padel',
      'Golf',
      'Equitazione',
      'Skateboard',
      'Boxe e arti marziali',
      'Sci',
      'Snowboard',
      'Pattinaggio',
    ],
  },
  {
    label: 'Articoli griffati',
    categories: [
      'Articoli griffati',
      'Borse griffate',
      'Scarpe griffate',
    ],
  },
  {
    label: 'Veicoli e altro',
    categories: [
      'Auto',
      'Moto',
      'Ricambi auto',
    ],
  },
];

/** Flat list of all categories (for validation / autocomplete). */
export const ALL_CATEGORIES: string[] = CATEGORY_GROUPS.flatMap(g => g.categories);
