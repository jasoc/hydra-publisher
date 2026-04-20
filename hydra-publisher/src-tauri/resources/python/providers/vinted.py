"""
Vinted.it provider — Selenium implementation.

Login: apre vinted.it usando il profilo Chrome persistente.
L'utente effettua login manualmente dal pannello Settings.

Publish flow (da implementare passo-passo):
  1. Naviga alla pagina di creazione articolo
  2. Upload foto
  3. Compila titolo, descrizione, prezzo
  4. Seleziona categoria e condizione
  5. Conferma / pubblica

I selettori del form stanno in selectors/vinted.yaml.
Aggiorna quello quando il sito cambia DOM — questo file non va toccato.
"""

import os
import time
from typing import Any

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from base import SeleniumProvider, FormFiller

# ── Selector config ───────────────────────────────────────────────────────────

# In dev mode the YAML lives in selectors/; in the bundled app everything is
# flattened into the same directory as this file.
_SELECTORS = os.path.join(os.path.dirname(__file__), "selectors", "vinted.yaml")
if not os.path.exists(_SELECTORS):
    _SELECTORS = os.path.join(os.path.dirname(__file__), "vinted.yaml")

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.vinted.it"
SELL_URL = f"{BASE_URL}/items/new"

# Mappa condizione articolo → label Vinted (aggiorna se cambiano le opzioni)
CONDITION_MAP: dict[str, str] = {
    "nuovo":              "Nuovo con cartellino",
    "new":                "Nuovo con cartellino",
    "come nuovo":         "Nuovo senza cartellino",
    "like new":           "Nuovo senza cartellino",
    "usato - come nuovo": "Nuovo senza cartellino",
    "ottimo":             "Ottimo stato",
    "usato - ottimo":     "Ottimo stato",
    "buono":              "Buono stato",
    "usato - buono":      "Buono stato",
    "usato":              "Buono stato",
}
DEFAULT_CONDITION = "Buono stato"

# Mappa categoria app → termine di ricerca Vinted.
# Il metodo _select_category digita il termine nel campo di ricerca del
# dropdown categorie e clicca il primo risultato.
# Chiavi: normalizzate lowercase. Valori: stringa esatta da cercare nel
# catalogo Vinted (deve restituire la categoria giusta come primo risultato).
CATEGORY_MAP: dict[str, str] = {
    # ── Donna ─────────────────────────────────────────────────────────────
    "abbigliamento donna":          "Vestiti",              # Donna > Vestiti
    "vestiti donna":                "Vestiti",
    "giacche donna":                "Abbigliamento da esterno",
    "cappotti donna":               "Abbigliamento da esterno",
    "maglioni donna":               "Maglioni e pullover",
    "abiti donna":                  "Abiti",
    "gonne":                        "Gonne",
    "top donna":                    "Top e t-shirt",
    "t-shirt donna":                "Top e t-shirt",
    "jeans donna":                  "Jeans",
    "pantaloni donna":              "Pantaloni e leggings",
    "pantaloncini donna":           "Pantaloncini e pantaloni corti",
    "costumi donna":                "Costumi da bagno",
    "lingerie":                     "Lingerie e indumenti da notte",
    "abbigliamento sportivo donna": "Abbigliamento sportivo",
    "scarpe donna":                 "Scarpe",               # Donna > Scarpe
    "stivali donna":                "Stivali",
    "sandali donna":                "Sandali",
    "tacchi":                       "Scarpe con tacchi alti",
    "sneakers donna":               "Scarpe da ginnastica",
    "borse":                        "Borse",                # Donna > Borse
    "zaini donna":                  "Zaini",
    "pochette":                     "Pochette",
    "portafogli donna":             "Portafogli",
    "accessori donna":              "Accessori",            # Donna > Accessori
    "cinture donna":                "Cinture",
    "cappelli donna":               "Cappelli e berretti",
    "gioielli donna":               "Gioielli",
    "sciarpe donna":                "Sciarpe e scialli",
    "occhiali da sole donna":       "Occhiali da sole",
    "orologi donna":                "Orologi",
    "bellezza":                     "Bellezza",             # Donna > Bellezza
    "make-up":                      "Make-up",
    "profumi":                      "Profumi",
    "cura viso":                    "Cura del viso",

    # ── Uomo ──────────────────────────────────────────────────────────────
    "abbigliamento uomo":           "Vestiti",              # Uomo > Vestiti
    "vestiti uomo":                 "Vestiti",
    "giacche uomo":                 "Abbigliamento da esterno",
    "cappotti uomo":                "Abbigliamento da esterno",
    "camicie uomo":                 "Camicie e t-shirt",
    "t-shirt uomo":                 "Camicie e t-shirt",
    "maglioni uomo":                "Maglioni e pullover",
    "completi uomo":                "Completi e blazer",
    "pantaloni uomo":               "Pantaloni",
    "jeans uomo":                   "Jeans",
    "pantaloncini uomo":            "Pantaloncini",
    "costumi uomo":                 "Costumi da bagno",
    "abbigliamento sportivo uomo":  "Abbigliamento sportivo",
    "scarpe uomo":                  "Scarpe",               # Uomo > Scarpe
    "stivali uomo":                 "Stivali",
    "sneakers uomo":                "Scarpe da ginnastica",
    "scarpe formali":               "Scarpe formali",
    "accessori uomo":               "Accessori",            # Uomo > Accessori
    "cinture uomo":                 "Cinture",
    "cappelli uomo":                "Cappelli e berretti",
    "gioielli uomo":                "Gioielli",
    "cravatte":                     "Cravatte e papillon",
    "orologi uomo":                 "Orologi",
    "occhiali da sole uomo":        "Occhiali da sole",

    # ── Bambini ───────────────────────────────────────────────────────────
    "bambini":                      "Bambini",
    "abbigliamento bambina":        "Abbigliamento bambina",
    "abbigliamento bambino":        "Abbigliamento bambino",
    "giocattoli":                   "Giocattoli",
    "peluche":                      "Peluche",
    "costruzioni":                  "Costruzioni e blocchetti",
    "bambole":                      "Bambole e accessori",
    "passeggini":                   "Passeggini e carrozzine",
    "seggiolini auto":              "Seggiolini auto",
    "arredamento bambini":          "Arredamento e decorazioni",

    # ── Casa ──────────────────────────────────────────────────────────────
    "casa":                         "Casa",
    "arredamento":                  "Accessori per la casa",
    "elettrodomestici cucina":      "Piccoli elettrodomestici da cucina",
    "pentole e padelle":            "Pentole",
    "utensili cucina":              "Utensili da cucina",
    "stoviglie":                    "Stoviglie",
    "biancheria letto":             "Biancheria da letto",
    "tende":                        "Tende e tapparelle",
    "tappeti":                      "Tappeti e tappetini",
    "candele":                      "Candele e profumi per la casa",
    "illuminazione":                "Illuminazione",
    "cornici":                      "Cornici per foto e quadri",
    "specchi":                      "Specchi",
    "vasi":                         "Vasi",
    "decorazioni parete":           "Decorazioni da parete",
    "materiale ufficio":            "Materiale per ufficio",
    "attrezzi":                     "Attrezzi e bricolage",
    "giardino":                     "Esterni e giardino",
    "animali":                      "Animali",

    # ── Elettronica ───────────────────────────────────────────────────────
    "elettronica":                  "Elettronica",
    "videogiochi":                  "Videogiochi e console",
    "console":                      "Console",
    "computer":                     "Computer e accessori",
    "portatili":                    "Computer portatili",
    "laptop":                       "Computer portatili",
    "desktop":                      "Computer desktop",
    "componenti pc":                "Parti e componenti del computer",
    "tastiere":                     "Tastiere e accessori",
    "mouse":                        "Mouse",
    "monitor":                      "Monitor e accessori",
    "stampanti":                    "Stampanti e accessori",
    "telefoni":                     "Telefoni cellulari",
    "cellulari":                    "Telefoni cellulari",
    "smartphone":                   "Telefoni cellulari",
    "accessori telefono":           "Parti e accessori per telefoni cellulari",
    "cover telefono":               "Parti e accessori per telefoni cellulari",
    "cuffie":                       "Cuffie e auricolari",
    "auricolari":                   "Cuffie e auricolari",
    "altoparlanti":                 "Altoparlanti portatili",
    "speaker":                      "Altoparlanti portatili",
    "audio":                        "Audio, cuffie e hi-fi",
    "fotocamere":                   "Fotocamere",
    "obiettivi":                    "Obiettivi",
    "tablet":                       "Tablet",
    "e-reader":                     "e-Reader",
    "televisori":                   "Televisori",
    "tv":                           "Televisori",
    "proiettori":                   "Proiettori",
    "smartwatch":                   "Smartwatch",
    "fitness tracker":              "Fitness tracker",
    "caricabatterie":               "Caricabatterie",
    "power bank":                   "Power bank",
    "cavi":                         "Cavi",

    # ── Intrattenimento ───────────────────────────────────────────────────
    "intrattenimento":              "Intrattenimento",
    "libri":                        "Libri",
    "narrativa":                    "Narrativa",
    "saggistica":                   "Saggistica",
    "fumetti":                      "Fumetti, manga e graphic novel",
    "manga":                        "Fumetti, manga e graphic novel",
    "riviste":                      "Riviste",
    "musica":                       "Musica",
    "vinile":                       "Dischi in vinile",
    "cd":                           "CD",
    "dvd":                          "DVD",
    "blu-ray":                      "Blu-ray",

    # ── Hobby e collezionismo ─────────────────────────────────────────────
    "hobby":                        "Hobby e collezionismo",
    "collezionismo":                "Hobby e collezionismo",
    "carte collezionabili":         "Carte collezionabili",
    "giochi da tavolo":             "Giochi da tavolo",
    "puzzle":                       "Puzzle",
    "monete":                       "Monete e banconote",
    "francobolli":                  "Francobolli",
    "strumenti musicali":           "Strumenti e attrezzature musicali",
    "chitarre":                     "Chitarre e bassi",
    "cucito":                       "Cucito, lavoro a maglia e ricamo",
    "pittura":                      "Pittura",

    # ── Sport ─────────────────────────────────────────────────────────────
    "sport":                        "Sport",
    "ciclismo":                     "Ciclismo",
    "biciclette":                   "Biciclette per bambini",
    "fitness":                      "Fitness, corsa e yoga",
    "corsa":                        "Corsa",
    "yoga":                         "Attrezzature per yoga e pilates",
    "campeggio":                    "Tende da campeggio e attrezzatura per dormire",
    "arrampicata":                  "Arrampicata e bouldering",
    "pesca":                        "Pesca e caccia",
    "nuoto":                        "Nuoto",
    "surf":                         "Tavole da SUP",
    "calcio":                       "Calcio",
    "basket":                       "Pallacanestro",
    "pallavolo":                    "Pallavolo",
    "tennis":                       "Tennis",
    "padel":                        "Padel",
    "golf":                         "Golf",
    "equitazione":                  "Equitazione",
    "skateboard":                   "Skateboard",
    "boxe":                         "Boxe e arti marziali",
    "sci":                          "Attrezzature da sci",
    "snowboard":                    "Attrezzatura da snowboar",
    "pattinaggio":                  "Accessori per pattinaggio di figura",

    # ── Articoli griffati ─────────────────────────────────────────────────
    "griffato":                     "Articoli griffati",
    "lusso":                        "Articoli griffati",
    "designer":                     "Articoli griffati",
    "borse griffate":               "Borse griffate",
    "scarpe griffate":              "Scarpe griffate",
}


class VintedProvider(SeleniumProvider):

    _filler = FormFiller(_SELECTORS)

    # ── Login ─────────────────────────────────────────────────────────────────

    def login(self, driver: Any) -> None:
        """Apre vinted.it — il login manuale è gestito dall'utente in Settings."""
        driver.get(BASE_URL)
        print("[Vinted] Browser aperto su vinted.it, pronto per login manuale.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _wait(self, driver: Any, timeout: int = 15) -> WebDriverWait:
        return WebDriverWait(driver, timeout)

    def _dismiss_cookie_banner(self, driver: Any) -> None:
        """Chiudi l'eventuale banner cookie / GDPR."""
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    "[data-testid='cookie-consent-accept'], "
                    "#onetrust-accept-btn-handler, "
                    "button[id*='accept']"
                ))
            )
            btn.click()
            print("[Vinted] Cookie banner chiuso.")
            time.sleep(0.5)
        except Exception:
            pass  # nessun banner presente

    def _upload_photos(self, article: dict, driver: Any) -> None:
        """Upload foto tramite l'input[type=file] nascosto dietro 'Carica le foto'."""
        photos = article.get("photos", [])
        if not photos:
            print("[Vinted] Nessuna foto da caricare, skip.")
            return

        folder = article.get("folderPath", "")

        # Costruisci percorsi assoluti
        paths = []
        for p in photos:
            full = p if os.path.isabs(p) else os.path.join(folder, p)
            if os.path.exists(full):
                paths.append(full)
            else:
                print(f"[Vinted] Foto non trovata, skip: {full}")
        if not paths:
            print("[Vinted] Nessuna foto valida trovata.")
            return

        # Trova l'input[type=file] nascosto e rendilo visibile
        wait = self._wait(driver)
        file_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )
        driver.execute_script(
            "arguments[0].style.display='block';"
            "arguments[0].style.visibility='visible';"
            "arguments[0].style.opacity='1';",
            file_input,
        )

        # send_keys accetta più file separati da \n
        file_input.send_keys("\n".join(paths))
        print(f"[Vinted] Caricate {len(paths)} foto.")
        # Attendi che i thumbnail vengano renderizzati
        time.sleep(2)

    def _fill_title(self, article: dict, driver: Any) -> None:
        """Compila il campo titolo."""
        title = article.get("name", "")
        if not title:
            return
        wait = self._wait(driver)
        el = wait.until(EC.presence_of_element_located((By.ID, "title")))
        el.clear()
        el.send_keys(title)
        print(f"[Vinted] Titolo: {title[:40]}")

    def _fill_description(self, article: dict, driver: Any) -> None:
        """Compila il campo descrizione."""
        desc = article.get("description", "")
        if not desc:
            return
        wait = self._wait(driver)
        el = wait.until(EC.presence_of_element_located((By.ID, "description")))
        el.clear()
        el.send_keys(desc)
        print(f"[Vinted] Descrizione: {desc[:40]}")

    def _fill_price(self, article: dict, driver: Any) -> None:
        """Compila il campo prezzo. TODO: implementare."""
        pass

    def _select_category(self, article: dict, driver: Any) -> None:
        """
        Seleziona la categoria tramite il dropdown con ricerca di Vinted.

        Flow:
        1. Clicca sull'input #category per aprire il dropdown
        2. Digita il termine di ricerca nel campo #catalog-search-input
        3. Attende che appaiano i risultati ([role="button"])
        4. Clicca il primo risultato
        """
        raw = article.get("category", "")
        if not raw:
            print("[Vinted] Nessuna categoria, skip.")
            return

        # Cerca nella mappa (case-insensitive)
        search_term = CATEGORY_MAP.get(raw.lower().strip(), raw)
        wait = self._wait(driver)

        # 1. Apri il dropdown cliccando sull'input categoria
        cat_input = wait.until(EC.element_to_be_clickable((By.ID, "category")))
        cat_input.click()
        time.sleep(0.5)

        # 2. Digita nel campo di ricerca
        search_input = wait.until(
            EC.presence_of_element_located((By.ID, "catalog-search-input"))
        )
        search_input.clear()
        search_input.send_keys(search_term)
        time.sleep(1)  # attendi risultati filtrati

        # 3. Clicca il primo risultato
        results = driver.find_elements(
            By.CSS_SELECTOR,
            ".category-scrollable-container [role='button']"
        )
        if results:
            driver.execute_script("arguments[0].click();", results[0])
            print(f"[Vinted] Categoria: '{search_term}' → cliccato primo risultato")
            time.sleep(0.5)
        else:
            print(f"[Vinted] Nessun risultato per categoria '{search_term}'")

    def _select_condition(self, article: dict, driver: Any) -> None:
        """Seleziona la condizione. TODO: implementare."""
        pass

    def _submit(self, driver: Any) -> None:
        """Clicca il pulsante di pubblicazione. TODO: implementare."""
        pass

    # ── Publish ───────────────────────────────────────────────────────────────

    def publish(self, article: dict, driver: Any) -> None:
        """
        Pubblica un articolo su vinted.it.

        Ogni step è in un metodo separato — implementali uno alla volta
        e testa singolarmente prima di passare al successivo.
        """
        name = article.get("name", "?")
        print(f"[Vinted] Pubblicazione: {name}")

        # 0. Naviga alla pagina di vendita
        driver.get(SELL_URL)
        time.sleep(2)

        print("[Vinted] Navigato a pagina vendita, pronto per compilare form.")

        

        # 0.1 Chiudi eventuali overlay
        self._dismiss_cookie_banner(driver)

        # 1. Upload foto
        self._upload_photos(article, driver)

        # 2. Titolo
        self._fill_title(article, driver)

        # 3. Descrizione
        self._fill_description(article, driver)

        # 4. Categoria
        self._select_category(article, driver)

        # 5. Condizione
        self._select_condition(article, driver)

        # 6. Prezzo
        self._fill_price(article, driver)

        # 7. Submit
        self._submit(driver)

        print(f"[Vinted] Completato: {name}")

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, article: dict, driver: Any) -> None:
        """Aggiornamento listing esistente. TODO: implementare."""
        raise NotImplementedError("VintedProvider.update() non ancora implementato")
