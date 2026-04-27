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
import random
import time
from typing import Any

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
# Mappa condizione app → data-testid Vinted nel dialog condizione.
# I valori sono gli ID nel DOM: condition-6 = Nuovo con cartellino,
# condition-1 = Nuovo senza cartellino, condition-2 = Ottime,
# condition-3 = Buone, condition-4 = Discrete.
CONDITION_TESTID: dict[str, str] = {
    "nuovo":                "condition-6",
    "usato - come nuovo":   "condition-1",
    "usato - buono":        "condition-2",
    "usato - accettabile":  "condition-3",
}
DEFAULT_CONDITION_TESTID = "condition-2"

# Mappa categoria app (da categories.model.ts) → termine di ricerca Vinted.
# Il metodo _select_category digita il termine nel campo di ricerca del
# dropdown categorie e clicca il primo risultato.
# Chiavi: stringa esatta dal modello app. Valori: stringa da cercare nel
# catalogo Vinted (deve restituire la categoria giusta come primo risultato).
CATEGORY_MAP: dict[str, str] = {
    # ── Abbigliamento donna ───────────────────────────────────────────
    "Vestiti donna":                "Vestiti",
    "Giacche e cappotti donna":     "Abbigliamento da esterno",
    "Maglioni e pullover donna":    "Maglioni e pullover",
    "Abiti donna":                  "Abiti",
    "Gonne":                        "Gonne",
    "Top e t-shirt donna":          "Top e t-shirt",
    "Jeans donna":                  "Jeans",
    "Pantaloni donna":              "Pantaloni e leggings",
    "Pantaloncini donna":           "Pantaloncini e pantaloni corti",
    "Costumi da bagno donna":       "Costumi da bagno",
    "Lingerie e pigiami":           "Lingerie e indumenti da notte",
    "Abbigliamento sportivo donna": "Abbigliamento sportivo",
    # ── Scarpe donna ──────────────────────────────────────────────────
    "Scarpe donna":                 "Scarpe",
    "Stivali donna":                "Stivali",
    "Sandali donna":                "Sandali",
    "Tacchi":                       "Scarpe con tacchi alti",
    "Sneakers donna":               "Scarpe da ginnastica",
    # ── Borse e accessori donna ───────────────────────────────────────
    "Borse":                        "Borse",
    "Zaini donna":                  "Zaini",
    "Pochette":                     "Pochette",
    "Portafogli donna":             "Portafogli",
    "Cinture donna":                "Cinture",
    "Cappelli donna":               "Cappelli e berretti",
    "Gioielli donna":               "Gioielli",
    "Sciarpe e scialli donna":      "Sciarpe e scialli",
    "Occhiali da sole donna":       "Occhiali da sole",
    "Orologi donna":                "Orologi",
    # ── Bellezza ──────────────────────────────────────────────────────
    "Make-up":                      "Make-up",
    "Profumi":                      "Profumi",
    "Cura del viso":                "Cura del viso",
    "Cura del corpo":               "Cura del corpo",
    # ── Abbigliamento uomo ────────────────────────────────────────────
    "Vestiti uomo":                 "Vestiti",
    "Giacche e cappotti uomo":      "Abbigliamento da esterno",
    "Camicie uomo":                 "Camicie e t-shirt",
    "T-shirt uomo":                 "Camicie e t-shirt",
    "Maglioni e pullover uomo":     "Maglioni e pullover",
    "Completi e blazer uomo":       "Completi e blazer",
    "Pantaloni uomo":               "Pantaloni",
    "Jeans uomo":                   "Jeans",
    "Pantaloncini uomo":            "Pantaloncini",
    "Costumi da bagno uomo":        "Costumi da bagno",
    "Abbigliamento sportivo uomo":  "Abbigliamento sportivo",
    # ── Scarpe uomo ───────────────────────────────────────────────────
    "Scarpe uomo":                  "Scarpe",
    "Stivali uomo":                 "Stivali",
    "Sneakers uomo":                "Scarpe da ginnastica",
    "Scarpe formali":               "Scarpe formali",
    # ── Accessori uomo ────────────────────────────────────────────────
    "Cinture uomo":                 "Cinture",
    "Cappelli uomo":                "Cappelli e berretti",
    "Gioielli uomo":                "Gioielli",
    "Cravatte e papillon":          "Cravatte e papillon",
    "Orologi uomo":                 "Orologi",
    "Occhiali da sole uomo":        "Occhiali da sole",
    # ── Bambini ───────────────────────────────────────────────────────
    "Abbigliamento bambina":        "Abbigliamento bambina",
    "Abbigliamento bambino":        "Abbigliamento bambino",
    "Scarpe bambini":               "Scarpe",
    "Giocattoli":                   "Giocattoli",
    "Peluche":                      "Peluche",
    "Costruzioni":                  "Costruzioni e blocchetti",
    "Bambole":                      "Bambole e accessori",
    "Passeggini e carrozzine":      "Passeggini e carrozzine",
    "Seggiolini auto":              "Seggiolini auto",
    "Arredamento bambini":          "Arredamento e decorazioni",
    # ── Casa e cucina ─────────────────────────────────────────────────
    "Arredamento":                  "Accessori per la casa",
    "Elettrodomestici cucina":      "Piccoli elettrodomestici da cucina",
    "Pentole e padelle":            "Pentole",
    "Utensili cucina":              "Utensili da cucina",
    "Stoviglie":                    "Stoviglie",
    "Biancheria letto":             "Biancheria da letto",
    "Tende e tapparelle":           "Tende e tapparelle",
    "Tappeti":                      "Tappeti e tappetini",
    "Candele e profumi casa":       "Candele e profumi per la casa",
    "Illuminazione":                "Illuminazione",
    "Cornici":                      "Cornici per foto e quadri",
    "Specchi":                      "Specchi",
    "Vasi":                         "Vasi",
    "Decorazioni parete":           "Decorazioni da parete",
    # ── Ufficio e casa ────────────────────────────────────────────────
    "Materiale ufficio":            "Materiale per ufficio",
    "Attrezzi e bricolage":         "Attrezzi e bricolage",
    "Giardino":                     "Esterni e giardino",
    "Animali":                      "Animali",
    # ── Elettronica ───────────────────────────────────────────────────
    "Videogiochi e console":        "Videogiochi e console",
    "Console":                      "Console",
    "Computer portatili":           "Computer portatili",
    "Computer desktop":             "Computer desktop",
    "Componenti PC":                "Parti e componenti del computer",
    "Tastiere":                     "Tastiere e accessori",
    "Mouse":                        "Mouse",
    "Monitor":                      "Monitor e accessori",
    "Stampanti":                    "Stampanti e accessori",
    "Smartphone":                   "Telefoni cellulari",
    "Accessori telefono":           "Parti e accessori per telefoni cellulari",
    "Cuffie e auricolari":          "Cuffie e auricolari",
    "Altoparlanti e speaker":       "Altoparlanti portatili",
    "Audio e hi-fi":                "Audio, cuffie e hi-fi",
    "Fotocamere":                   "Fotocamere",
    "Obiettivi":                    "Obiettivi",
    "Tablet":                       "Tablet",
    "E-reader":                     "e-Reader",
    "Televisori":                   "Televisori",
    "Proiettori":                   "Proiettori",
    "Smartwatch":                   "Smartwatch",
    "Fitness tracker":              "Fitness tracker",
    "Caricabatterie e power bank":  "Caricabatterie",
    "Cavi e adattatori":            "Cavi",
    # ── Intrattenimento ───────────────────────────────────────────────
    "Libri":                        "Libri",
    "Narrativa":                    "Narrativa",
    "Saggistica":                   "Saggistica",
    "Fumetti e manga":              "Fumetti, manga e graphic novel",
    "Riviste":                      "Riviste",
    "Musica":                       "Musica",
    "Vinile":                       "Dischi in vinile",
    "CD":                           "CD",
    "DVD e Blu-ray":                "DVD",
    # ── Hobby e collezionismo ─────────────────────────────────────────
    "Carte collezionabili":         "Carte collezionabili",
    "Giochi da tavolo":             "Giochi da tavolo",
    "Puzzle":                       "Puzzle",
    "Monete e banconote":           "Monete e banconote",
    "Francobolli":                  "Francobolli",
    "Strumenti musicali":           "Strumenti e attrezzature musicali",
    "Chitarre":                     "Chitarre e bassi",
    "Arte e artigianato":           "Arte e creatività",
    # ── Sport ─────────────────────────────────────────────────────────
    "Ciclismo":                     "Ciclismo",
    "Fitness e palestra":           "Fitness, corsa e yoga",
    "Corsa":                        "Corsa",
    "Yoga e pilates":               "Attrezzature per yoga e pilates",
    "Campeggio":                    "Tende da campeggio e attrezzatura per dormire",
    "Arrampicata":                  "Arrampicata e bouldering",
    "Pesca":                        "Pesca e caccia",
    "Nuoto":                        "Nuoto",
    "Surf e SUP":                   "Tavole da SUP",
    "Calcio":                       "Calcio",
    "Basket":                       "Pallacanestro",
    "Pallavolo":                    "Pallavolo",
    "Tennis":                       "Tennis",
    "Padel":                        "Padel",
    "Golf":                         "Golf",
    "Equitazione":                  "Equitazione",
    "Skateboard":                   "Skateboard",
    "Boxe e arti marziali":         "Boxe e arti marziali",
    "Sci":                          "Attrezzature da sci",
    "Snowboard":                    "Attrezzatura da snowboard",
    "Pattinaggio":                  "Accessori per pattinaggio di figura",
    # ── Articoli griffati ─────────────────────────────────────────────
    "Articoli griffati":            "Articoli griffati",
    "Borse griffate":               "Borse griffate",
    "Scarpe griffate":              "Scarpe griffate",
    # ── Veicoli e altro ───────────────────────────────────────────────
    "Auto":                         "Auto",
    "Moto":                         "Moto",
    "Ricambi auto":                 "Auto",
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

    def _human_pause(self, base: float = 0.8, jitter: float = 1.5) -> None:
        """Pausa con jitter per ridurre pattern meccanici ripetibili."""
        delay = max(0.2, base + random.uniform(0.0, jitter))
        time.sleep(delay)

    def _human_type(self, element: Any, text: str, min_delay: float = 0.04, max_delay: float = 0.14) -> None:
        """Digita testo carattere per carattere con ritmo umano.

        Ogni carattere ha un ritardo random, con pause più lunghe dopo
        spazi e punteggiatura (come farebbe una persona vera).
        """
        for i, char in enumerate(text):
            element.send_keys(char)
            # Pausa più lunga dopo spazio/punteggiatura (come un umano)
            if char in ' .,;:!?\n':
                time.sleep(random.uniform(min_delay * 2, max_delay * 3))
            else:
                time.sleep(random.uniform(min_delay, max_delay))
            # Micro-pausa occasionale ("pensare") ogni 15-40 caratteri
            if i > 0 and i % random.randint(15, 40) == 0:
                time.sleep(random.uniform(0.3, 0.8))

    def _ensure_not_flagged(self, driver: Any) -> None:
        """Interrompe il flusso se Vinted mostra il banner anti-automazione."""
        try:
            page = (driver.page_source or "").lower()
        except Exception:
            return

        suspicious_markers = [
            "we've noticed unusual activity",
            "resembles automated or suspicious behaviour",
            "unusual activity with your session",
            "attivit\u00e0 insolita",
            "attivit\u00e0 sospetta",
            "comportamento automatizzato",
            "verifica di sicurezza",
            "captcha",
            "recaptcha",
            "hcaptcha",
            "cf-challenge",
            "just a moment",
        ]
        if any(marker in page for marker in suspicious_markers):
            raise RuntimeError(
                "Vinted ha segnalato attività sospetta nella sessione corrente. "
                "Metti in pausa il batch e riprova più tardi con ritmo più lento."
            )

    def _field_present(self, driver: Any, field_id: str, timeout: float = 2.5) -> bool:
        """Rileva se un campo input/select con id specifico è presente nel form."""
        end = time.time() + timeout
        while time.time() < end:
            if driver.find_elements(By.ID, field_id):
                return True
            time.sleep(0.2)
        return False

    def _wait_optional_fields_after_category(self, driver: Any, timeout: float = 4.0) -> None:
        """Dopo la categoria aspetta che eventuali campi dinamici vengano renderizzati."""
        end = time.time() + timeout
        dynamic_ids = ["brand", "condition", "color", "size"]
        while time.time() < end:
            if any(driver.find_elements(By.ID, field_id) for field_id in dynamic_ids):
                # piccolo buffer per React re-render / clickability
                self._human_pause(0.4, 0.6)
                return
            time.sleep(0.2)

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
            self._human_pause(0.8, 1.2)
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
        # Attendi che i thumbnail vengano renderizzati (1 foto ≈ 2-3s)
        self._human_pause(2.0 + len(paths) * 0.8, 2.0)

    def _fill_title(self, article: dict, driver: Any) -> None:
        """Compila il campo titolo."""
        title = article.get("name", "")
        if not title:
            return
        wait = self._wait(driver)
        el = wait.until(EC.presence_of_element_located((By.ID, "title")))
        el.click()
        self._human_pause(0.3, 0.4)
        el.clear()
        self._human_type(el, title)
        print(f"[Vinted] Titolo: {title[:40]}")
        self._human_pause(0.5, 0.8)

    def _fill_description(self, article: dict, driver: Any) -> None:
        """Compila il campo descrizione."""
        desc = article.get("description", "")
        if not desc:
            return
        wait = self._wait(driver)
        el = wait.until(EC.presence_of_element_located((By.ID, "description")))
        el.click()
        self._human_pause(0.3, 0.5)
        el.clear()
        self._human_type(el, desc)
        print(f"[Vinted] Descrizione: {desc[:40]}")
        self._human_pause(0.6, 1.0)

    def _fill_price(self, article: dict, driver: Any) -> None:
        """Compila il campo prezzo."""
        price = article.get("price")
        if price is None:
            return
        wait = self._wait(driver)
        el = wait.until(EC.presence_of_element_located((By.ID, "price")))
        el.click()
        self._human_pause(0.3, 0.4)
        el.clear()
        price_str = str(int(price)) if isinstance(price, float) and price == int(price) else str(price)
        self._human_type(el, price_str)
        print(f"[Vinted] Prezzo: {price}")
        self._human_pause(0.5, 0.7)

    def _select_category(self, article: dict, driver: Any) -> None:
        """
        Seleziona la categoria tramite il dropdown con ricerca di Vinted.

        Flow:
        1. Clicca sull'input #category per aprire il dropdown
        2. Digita il termine di ricerca nel campo #catalog-search-input
        3. Attende che appaiano i risultati di ricerca (id="catalog-search-*-result")
        4. Clicca il primo risultato (sono già categorie foglia con radio button)
        """
        raw = (article.get("category") or "").strip()
        if not raw:
            print("[Vinted] Nessuna categoria, skip.")
            return

        # Cerca nella mappa (exact match, le chiavi sono Title Case come nel modello app)
        search_term = CATEGORY_MAP.get(raw) or raw
        wait = self._wait(driver)

        # 1. Apri il dropdown cliccando sull'input categoria
        cat_input = wait.until(EC.element_to_be_clickable((By.ID, "category")))
        cat_input.click()
        self._human_pause(0.8, 1.0)

        # 2. Digita nel campo di ricerca
        search_input = wait.until(
            EC.presence_of_element_located((By.ID, "catalog-search-input"))
        )
        search_input.clear()
        self._human_type(search_input, search_term)
        self._human_pause(1.5, 1.5)  # attendi risultati filtrati

        # 3. Clicca il primo risultato di ricerca
        results = driver.find_elements(
            By.CSS_SELECTOR,
            "[id^='catalog-search-'][id$='-result'][role='button']"
        )
        if results:
            label = results[0].text.strip().split("\n")[0][:50]
            driver.execute_script("arguments[0].click();", results[0])
            print(f"[Vinted] Categoria: '{search_term}' → '{label}'")
            self._human_pause(0.8, 1.2)
        else:
            print(f"[Vinted] Nessun risultato per categoria '{search_term}'")

    def _select_condition(self, article: dict, driver: Any) -> None:
        """Seleziona la condizione tramite il dialog Vinted.

        Flow:
        1. Clicca #condition per aprire il dialog
        2. Clicca l'elemento con data-testid corrispondente alla condizione
        """
        raw = (article.get("condition") or "").strip().lower()
        testid = CONDITION_TESTID.get(raw, DEFAULT_CONDITION_TESTID)
        wait = self._wait(driver)

        # 1. Apri dialog
        cond_btn = wait.until(EC.element_to_be_clickable((By.ID, "condition")))
        cond_btn.click()
        self._human_pause(0.8, 1.0)

        # 2. Clicca l'opzione giusta
        option = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, f"[data-testid='{testid}']"))
        )
        option.click()
        print(f"[Vinted] Condizione: {raw or '(default)'} → {testid}")
        self._human_pause(0.6, 1.0)

    def _select_brand(self, article: dict, driver: Any) -> None:
        """Seleziona il brand tramite il dropdown con ricerca.

        Flow:
        1. Clicca #brand per aprire il dropdown
        2. Se brand vuoto → clicca #empty-brand e torna
        3. Se brand valorizzato:
           - Digita nel campo #brand-search-input (nativo event)
           - Aspetta filtraggio DDL
           - Controlla se appare il bottone "Utilizza X come brand" (#custom-select-brand)
             * Se esiste e visibile → clickalo (permette brand personalizzato)
             * Se non esiste → seleziona il PRIMO brand dalla lista
        
        Retry: Se brand è valorizzato, riprova fino a 3 volte in caso di fallimento.
        """
        brand = (article.get("brand") or "").strip()
        wait = self._wait(driver)

        # Se brand è vuoto, seleziona "Nessun brand" e torna (nessun retry)
        if not brand:
            try:
                brand_btn = wait.until(EC.element_to_be_clickable((By.ID, "brand")))
                brand_btn.click()
                wait.until(EC.presence_of_element_located((By.ID, "brand-search-input")))
                empty = wait.until(EC.element_to_be_clickable((By.ID, "empty-brand")))
                driver.execute_script("arguments[0].click();", empty)
                print("[Vinted] Brand: nessuno (empty-brand)")
            except Exception as e:
                print(f"[Vinted] Brand: skip (nessun brand, errore: {e})")
            self._human_pause(0.3, 0.6)
            return

        # Brand valorizzato: retry fino a 3 volte
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self._select_brand_attempt(article, driver, attempt, max_attempts)
                return  # successo
            except Exception as e:
                if attempt < max_attempts:
                    print(f"[Vinted] Brand tentativo {attempt}/{max_attempts} fallito: {e}, riprovo...")
                    self._human_pause(0.8, 0.8)  # attesa prima di retry
                else:
                    print(f"[Vinted] Brand: fallito dopo {max_attempts} tentativi")
                    raise RuntimeError(f"Impossibile selezionare brand '{brand}' dopo {max_attempts} tentativi: {e}")

    def _select_brand_attempt(self, article: dict, driver: Any, attempt: int, max_attempts: int) -> None:
        """Tentativo singolo di selezione brand (usato internamente con retry)."""
        brand = article.get("brand", "").strip()
        wait = self._wait(driver)

        # 1. Apri dropdown brand
        brand_btn = wait.until(EC.element_to_be_clickable((By.ID, "brand")))
        brand_btn.click()
        
        # Aspetta che il dropdown si apra (ricerca diventa visibile)
        wait.until(EC.presence_of_element_located((By.ID, "brand-search-input")))
        self._human_pause(0.5, 0.6)

        # 2. Riempi il campo di ricerca
        search_input = wait.until(
            EC.presence_of_element_located((By.ID, "brand-search-input"))
        )
        search_input.clear()
        self._human_type(search_input, brand)
        self._human_pause(1.5, 1.5)  # attendi filtraggio DOM

        # 3. Aspetta che il custom brand appaia (max 3s)
        custom_appeared = False
        try:
            WebDriverWait(driver, 3).until(
                lambda d: d.find_element(By.ID, "custom-select-brand").is_displayed()
            )
            custom_appeared = True
        except Exception:
            pass

        if custom_appeared:
            # Bottone custom brand è disponibile → usalo
            custom_btn = driver.find_element(By.ID, "custom-select-brand")
            label = custom_btn.text.strip()[:80]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", custom_btn)
            driver.execute_script("arguments[0].click();", custom_btn)
            print(f"[Vinted] Brand: '{brand}' → custom brand '{label}' (tentativo {attempt}/{max_attempts})")
            self._human_pause(0.8, 1.0)
            return

        # 4. Se custom brand non appare, seleziona il PRIMO brand dalla lista filtrata
        all_buttons = driver.find_elements(
            By.CSS_SELECTOR,
            "div[id^='brand-'][role='button'], div[id^='suggested-brand-'][role='button']"
        )
        visible_buttons = [el for el in all_buttons if el.is_displayed()]

        if visible_buttons:
            # Clicca il PRIMO bottone
            target = visible_buttons[0]
            label = target.text.strip()[:80]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
            driver.execute_script("arguments[0].click();", target)
            print(f"[Vinted] Brand: '{brand}' → primo risultato filtrato '{label}' (tentativo {attempt}/{max_attempts})")
        else:
            # Nessun risultato → fallback a empty-brand
            try:
                empty = wait.until(EC.element_to_be_clickable((By.ID, "empty-brand")))
                driver.execute_script("arguments[0].click();", empty)
                print(f"[Vinted] Brand: '{brand}' non trovato, fallback empty-brand (tentativo {attempt}/{max_attempts})")
            except Exception:
                raise RuntimeError(f"Brand '{brand}': nessuna opzione disponibile e empty-brand non trovato")
        self._human_pause(0.8, 1.0)

    def _select_size_middle(self, driver: Any) -> None:
        """Seleziona la taglia scegliendo l'opzione centrale disponibile nel popup."""
        wait = self._wait(driver)

        # 1. Apri dialog taglia
        size_btn = wait.until(EC.element_to_be_clickable((By.ID, "size")))
        size_btn.click()
        self._human_pause(0.8, 1.0)

        # 2. Raccogli opzioni disponibili e clicca quella centrale
        try:
            wait.until(
                lambda d: len([
                    el for el in d.find_elements(By.CSS_SELECTOR, "[id^='size-'][role='button']")
                    if el.is_displayed()
                ]) > 0
            )
        except Exception:
            pass

        options = [
            el for el in driver.find_elements(By.CSS_SELECTOR, "[id^='size-'][role='button']")
            if el.is_displayed()
        ]
        if not options:
            print("[Vinted] Taglia: nessuna opzione trovata")
            return

        mid_idx = len(options) // 2
        target = options[mid_idx]
        label = target.text.strip().split("\n")[0][:50]
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
        driver.execute_script("arguments[0].click();", target)
        print(f"[Vinted] Taglia: selezionata opzione centrale ({mid_idx + 1}/{len(options)}) '{label}'")
        self._human_pause(0.8, 1.0)

    def _select_colors(self, article: dict, driver: Any) -> None:
        """Seleziona i colori hardcoded: Grigio (color-3) + Cachi (color-16).

        Flow:
        1. Clicca #color per aprire il dialog
        2. Clicca [data-testid='color-3'] (Grigio)
        3. Clicca [data-testid='color-16'] (Cachi)
        4. Chiudi il popup per applicare i colori
        """
        wait = self._wait(driver)

        # 1. Apri dialog colori
        color_btn = wait.until(EC.element_to_be_clickable((By.ID, "color")))
        color_btn.click()
        self._human_pause(0.8, 1.0)

        # 2. Seleziona Grigio
        try:
            grigio = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='color-3']"))
            )
            grigio.click()
            print("[Vinted] Colore: Grigio (color-3)")
        except Exception:
            print("[Vinted] Colore Grigio non trovato")

        # 3. Seleziona Cachi
        try:
            cachi = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='color-16']"))
            )
            cachi.click()
            print("[Vinted] Colore: Cachi (color-16)")
        except Exception:
            print("[Vinted] Colore Cachi non trovato")

        self._human_pause(0.6, 0.8)
        
        # 4. Chiudi il popup premendo Escape per applicare i colori
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        self._human_pause(0.8, 1.0)
        print("[Vinted] Popup colori chiuso")

    def _submit(self, driver: Any) -> None:
        """Clicca il pulsante 'Carica' per pubblicare l'annuncio."""
        wait = self._wait(driver)
        
        # Aspetta che il bottone "Carica" sia abilitato (non disabilitato)
        try:
            submit_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='upload-form-save-button']"))
            )
            # Ulteriore attesa per assicurare che il form sia completamente pronto
            self._human_pause(1.5, 2.0)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            self._human_pause(0.5, 0.8)
            driver.execute_script("arguments[0].click();", submit_btn)
            print("[Vinted] Click su bottone 'Carica'")
            self._human_pause(2.0, 2.0)  # attendi redirect
        except Exception as e:
            raise RuntimeError(f"Vinted submit fallito: {e}")

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
        self._human_pause(2.5, 2.5)
        self._ensure_not_flagged(driver)

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
        self._ensure_not_flagged(driver)

        # 4.1 I campi extra appaiono dinamicamente dopo la categoria.
        self._wait_optional_fields_after_category(driver)

        # 5. Campi dinamici: compila solo quelli presenti nel form corrente.
        if self._field_present(driver, "brand"):
            self._select_brand(article, driver)
            self._human_pause(0.8, 1.2)
        else:
            print("[Vinted] Campo brand non presente, skip")

        if self._field_present(driver, "condition"):
            self._select_condition(article, driver)
            self._human_pause(0.8, 1.2)
        else:
            print("[Vinted] Campo condition non presente, skip")

        if self._field_present(driver, "color"):
            self._select_colors(article, driver)
            self._human_pause(0.8, 1.2)
        else:
            print("[Vinted] Campo color non presente, skip")

        if self._field_present(driver, "size"):
            self._select_size_middle(driver)
            self._human_pause(0.8, 1.2)
        else:
            print("[Vinted] Campo size non presente, skip")
        self._ensure_not_flagged(driver)

        # 6. Prezzo
        self._fill_price(article, driver)
        self._human_pause(1.0, 1.5)
        self._ensure_not_flagged(driver)

        # 7. Submit
        self._submit(driver)

        print(f"[Vinted] Completato: {name}")

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, article: dict, driver: Any) -> None:
        """Aggiornamento listing esistente. TODO: implementare."""
        raise NotImplementedError("VintedProvider.update() non ancora implementato")
