# Aggiungere un nuovo provider Selenium — flusso completo

## Il problema

Ogni sito ha il suo DOM. Trovare selettori a mano (ispeziona elemento, copi la classe CSS, il sito fa un deploy e la classe cambia) è lento e fragile.

## La soluzione: tre livelli separati

```
providers/selectors/<sito>.yaml   ← SOLO selettori, nessuna logica
providers/<sito>.py               ← SOLO logica (login + casi speciali)
base.py → FormFiller              ← fa il lavoro di riempimento, legge il YAML
```

Quando il sito cambia DOM → aggiorni solo il YAML.
Quando cambia la logica di login → aggiorni solo il `.py`.
Il `FormFiller` non si tocca mai.

---

## Flusso di lavoro completo

### Step 1 — Registra le interazioni con il form

```bash
./playwright/record.sh vinted
# oppure con URL diretto:
./playwright/record.sh https://www.vinted.it/items/new
```

Si apre un browser. Interagisci col form come faresti normalmente (compila tutti i campi, clicca tutti i bottoni fino al submit). Chiudi il browser quando hai finito.

Il file viene salvato in `playwright/recorded/vinted_<timestamp>.py`.

### Step 2 — Genera il YAML (automatico)

`record.sh` chiama già `extract.py` in automatico al termine della registrazione.
Se vuoi rigenerarlo manualmente:

```bash
python playwright/extract.py playwright/recorded/vinted_20260324_233026.py
# oppure con provider esplicito:
python playwright/extract.py playwright/recorded/vinted_xxx.py --provider vinted
```

Output: `providers/selectors/vinted.yaml` con i selettori già convertiti per Selenium.

### Step 3 — Controlla i TODO nel YAML

Il file generato ha dei `# TODO` dove `extract.py` non è riuscito a indovinare:
- il mapping campo → `article_key` (name/price/description/…)
- dropdown multi-step (categoria, condizione) — appaiono come click separati da riorganizzare

Esempio di YAML generato e da editare:

```yaml
publish_url: "https://www.vinted.it/items/new"

fields:
  - id: title
    article_key: name             # ← indovinato automaticamente
    type: text
    xpath: '//input[@aria-label="Titolo"] | //input[@name="title"]'

  - id: price
    article_key: price
    type: text
    xpath: '//input[@aria-label="Prezzo"] | //input[@name="price"]'

  - id: unknown_field
    article_key: # TODO: name | description | price | category | condition | photos
    type: text
    xpath: '//input[@aria-label="Campo sconosciuto"]'

buttons:
  - id: carica
    xpath: '//button[contains(.,"Carica")]'
    wait_after: 2
```

### Step 4 — Crea il provider Python (solo la prima volta)

Copia `vinted.py` come template e cambia solo il nome:

```python
# providers/nuovosito.py
import os, time
from typing import Any
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from base import SeleniumProvider, FormFiller

_SELECTORS = os.path.join(os.path.dirname(__file__), "selectors", "nuovosito.yaml")
_LOGGED_IN = (By.XPATH, '// ... selettore navbar loggato ...')

class NuovoSitoProvider(SeleniumProvider):
    _filler = FormFiller(_SELECTORS)

    def login(self, driver: Any) -> None:
        driver.get("https://www.nuovosito.it")
        # accetta cookie, aspetta login manuale se necessario
        try:
            WebDriverWait(driver, 180).until(EC.presence_of_element_located(_LOGGED_IN))
        except Exception:
            raise RuntimeError("Timeout login NuovoSito.")

    def publish(self, article: dict, driver: Any) -> None:
        driver.get(self._filler.publish_url)
        time.sleep(2)
        self._filler.fill(article, driver)
```

### Step 5 — Registra in server.py

```python
from nuovosito import NuovoSitoProvider

PROVIDERS = {
    ...
    "nuovosito": NuovoSitoProvider(),
}
```

### Step 6 — Aggiungi al frontend

In `src/app/models/platform.model.ts` aggiungi l'id `"nuovosito"` alla lista delle piattaforme note.

---

## Quando il sito cambia DOM

Ripeti solo step 1 + 2. Il Python non si tocca.

```bash
./playwright/record.sh vinted     # ri-registra
# extract.py sovrascrive il YAML automaticamente
# controlla i TODO rimasti
```

---

## Gerarchia dei selettori (dalla più stabile alla meno stabile)

| Tipo | Esempio | Stabilità |
|------|---------|-----------|
| `data-testid` / `data-cy` | `[data-testid="title-input"]` | ★★★★★ |
| `aria-label` / `role` | `[@aria-label="Titolo"]` | ★★★★☆ |
| `name` dell'input | `[@name="title"]` | ★★★★☆ |
| Testo visibile | `[contains(.,"Carica")]` | ★★★☆☆ |
| `id` | `[@id="title"]` | ★★★☆☆ (spesso generato) |
| Classi CSS | `.x1lliihq.x6ikm8r` | ★☆☆☆☆ cambiano ad ogni deploy |
| Struttura DOM (nth-child) | `div > div:nth-child(3) > input` | ☆☆☆☆☆ evitare |

---

## FormFiller — reference

Definito in `providers/base.py`. Legge il YAML e riempie il form.

**Tipi di campo supportati:**

| `type` | Comportamento |
|--------|--------------|
| `text` | `input.clear()` + `send_keys(value)` |
| `textarea` | `textarea.clear()` + `send_keys(value)` |
| `file` | rende visibile l'input, `send_keys` con i path delle foto separati da `\n` |

**Localizzatori supportati nel YAML:**

```yaml
xpath: '//input[@name="title"]'          # XPath Selenium
css:   'input[data-testid="title-input"]' # CSS selector
```

**Bottoni:**

```yaml
buttons:
  - id: next
    xpath: '//button[contains(.,"Avanti")]'
    wait_after: 1.5    # secondi di attesa dopo il click (default: 1)
  - id: submit
    xpath: '//button[contains(.,"Carica")]'
    wait_after: 2
```

---

## Struttura file

```
playwright/
├── venv/                          venv con playwright installato
├── record.sh                      avvia codegen + chiama extract.py
├── extract.py                     converte recorded/*.py → selectors/*.yaml
└── recorded/                      output di codegen (non committare)

hydra-publisher/src-tauri/resources/python/providers/
├── base.py                        Provider, SeleniumProvider, FormFiller
├── selectors/
│   ├── vinted.yaml                ← modifica qui quando il DOM cambia
│   └── <nuovosito>.yaml
├── vinted.py                      provider thin (login + publish con FormFiller)
└── server.py                      registry PROVIDERS
```
