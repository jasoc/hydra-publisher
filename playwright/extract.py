#!/usr/bin/env python3
"""
extract.py — converte un file playwright codegen in un selectors YAML per Selenium.

Uso:
  python playwright/extract.py playwright/recorded/vinted_20260324_233026.py
  python playwright/extract.py playwright/recorded/vinted_xxx.py --provider vinted
  python playwright/extract.py playwright/recorded/vinted_xxx.py --out path/custom.yaml

Il file generato va in:
  hydra-publisher/src-tauri/resources/python/providers/selectors/<provider>.yaml

Cosa fa:
  - Parsa le chiamate playwright: get_by_role, get_by_label, locator, fill, click
  - Converte i locatori playwright in XPath/CSS Selenium
  - Tenta di indovinare l'article_key (name, price, description, …) dal contesto
  - Genera un YAML pronto da editare, con i TODO dove non riesce a indovinare

Limitazioni:
  - I dropdown multi-step (categoria, condizione) NON vengono catturati come
    semplici field — appaiono come bottoni click separati, da riorganizzare a mano.
  - Verifica sempre i selettori generati prima di usarli in produzione.
"""

import argparse
import ast
import os
import re
import sys
from pathlib import Path
from textwrap import dedent

# ── Mappatura nome-campo → article_key ───────────────────────────────────────
# Se il nome del campo (aria-label, placeholder, label text) contiene una di
# queste stringhe (case-insensitive), viene assegnato quell'article_key.
_KEY_HINTS: list[tuple[str, str]] = [
    ("titolo",      "name"),
    ("title",       "name"),
    ("nome",        "name"),
    ("descrizione", "description"),
    ("description", "description"),
    ("prezzo",      "price"),
    ("price",       "price"),
    ("categoria",   "category"),
    ("category",    "category"),
    ("condizione",  "condition"),
    ("condition",   "condition"),
    ("foto",        "photos"),
    ("photo",       "photos"),
    ("immagine",    "photos"),
    ("image",       "photos"),
]

_FIELD_TYPES: dict[str, str] = {
    "name":        "text",
    "description": "textarea",
    "price":       "text",
    "category":    "text",
    "condition":   "text",
    "photos":      "file",
}


def _guess_key(label: str) -> str | None:
    low = label.lower()
    for hint, key in _KEY_HINTS:
        if hint in low:
            return key
    return None


# ── Playwright locator → XPath/CSS ───────────────────────────────────────────

def _playwright_to_xpath(locator_source: str) -> tuple[str, str]:
    """
    Convert a playwright locator expression to (kind, selector).
    kind is 'xpath' or 'css'.

    Handles:
      get_by_role("textbox", name="X")   → xpath //input[@aria-label="X"]
      get_by_role("button",  name="X")   → xpath //button[contains(.,"X")]
      get_by_label("X")                  → xpath //*[@aria-label="X"]
      get_by_placeholder("X")            → xpath //input[@placeholder="X"]
      locator('[data-testid="X"]')       → css   [data-testid="X"]
      locator('input[name="X"]')         → css   input[name="X"]
      locator('//xpath')                 → xpath //xpath
    """
    src = locator_source.strip()

    # get_by_role
    m = re.match(r'get_by_role\(["\'](\w+)["\'](?:,\s*name=["\']([^"\']+)["\'])?\)', src)
    if m:
        role, name = m.group(1), m.group(2) or ""
        if role == "textbox":
            if name:
                return "xpath", f'//input[@aria-label="{name}"] | //input[@name="{name.lower()}"] | //textarea[@aria-label="{name}"]'
            return "xpath", '//input[@type="text"] | //textarea'
        if role == "button":
            if name:
                return "xpath", f'//button[contains(.,"{name}")] | //*[@role="button"][contains(.,"{name}")]'
            return "xpath", '//button'
        if name:
            return "xpath", f'//*[@role="{role}"][@aria-label="{name}"]'
        return "xpath", f'//*[@role="{role}"]'

    # get_by_label
    m = re.match(r'get_by_label\(["\']([^"\']+)["\']\)', src)
    if m:
        label = m.group(1)
        return "xpath", f'//label[contains(.,"{label}")]//input | //label[contains(.,"{label}")]//textarea | //*[@aria-label="{label}"]'

    # get_by_placeholder
    m = re.match(r'get_by_placeholder\(["\']([^"\']+)["\']\)', src)
    if m:
        return "xpath", f'//input[@placeholder="{m.group(1)}"] | //textarea[@placeholder="{m.group(1)}"]'

    # locator('...')
    m = re.match(r'locator\(["\']([^"\']+)["\']\)', src)
    if m:
        sel = m.group(1)
        if sel.startswith("//") or sel.startswith("(//"):
            return "xpath", sel
        return "css", sel

    return "xpath", f'# TODO: convertire manualmente → {src}'


# ── Parser del file codegen ───────────────────────────────────────────────────

class Action:
    def __init__(self, locator: str, method: str, value: str = ""):
        self.locator = locator   # es. get_by_role("textbox", name="Titolo")
        self.method = method     # fill | click | type | send_keys
        self.value = value       # valore passato a fill()

    def __repr__(self):
        return f"Action({self.method} {self.locator!r} = {self.value!r})"


def _parse_codegen(source: str) -> list[Action]:
    """
    Parse playwright codegen Python source and extract all fill/click actions.

    Handles both single-line and chained calls:
      page.get_by_role("textbox", name="X").fill("value")
      page.locator('[data-testid="X"]').click()
    """
    actions: list[Action] = []

    # Match: page.<locator_expr>.<method>(<args>)
    pattern = re.compile(
        r'page\.((?:get_by_\w+|locator)\([^)]+\))'   # locator
        r'\.'
        r'(\w+)'                                       # method
        r'\(([^)]*)\)',                                # args
        re.MULTILINE,
    )

    for m in pattern.finditer(source):
        locator_raw = m.group(1)
        method = m.group(2)
        args_raw = m.group(3).strip()

        if method not in ("fill", "click", "type", "press", "send_keys", "check"):
            continue

        # extract string value from fill("value") — strip quotes
        value = ""
        if args_raw:
            vm = re.match(r'^["\'](.*)["\']\s*$', args_raw)
            value = vm.group(1) if vm else args_raw

        actions.append(Action(locator_raw, method, value))

    return actions


# ── YAML generator ────────────────────────────────────────────────────────────

def _generate_yaml(actions: list[Action], provider_id: str, publish_url: str) -> str:
    fields: list[str] = []
    buttons: list[str] = []
    seen_keys: set[str] = set()

    for action in actions:
        kind, selector = _playwright_to_xpath(action.locator)

        # derive a human label from the locator for key-guessing
        label_match = re.search(r'name=["\']([^"\']+)["\']', action.locator)
        label = label_match.group(1) if label_match else action.value

        article_key = _guess_key(label) if label else None

        if action.method == "click":
            # Button
            btn_label = label or "button"
            buttons.append(dedent(f"""\
              - id: {btn_label.lower().replace(" ", "_")}
                {kind}: '{selector}'
                wait_after: 1
            """))

        elif action.method in ("fill", "type", "send_keys"):
            if article_key and article_key in seen_keys:
                continue  # duplicate, skip
            field_id = article_key or label.lower().replace(" ", "_") if label else "unknown"
            field_type = _FIELD_TYPES.get(article_key, "text") if article_key else "text"
            key_line = f"    article_key: {article_key}" if article_key else "    article_key: # TODO: name | description | price | category | condition | photos"

            fields.append(dedent(f"""\
              - id: {field_id}
            {key_line}
                type: {field_type}
                {kind}: '{selector}'
            """))
            if article_key:
                seen_keys.add(article_key)

    fields_yaml = "\n  ".join(f.strip() for f in fields) if fields else "  # TODO: nessun campo rilevato — registra il form con codegen"
    buttons_yaml = "\n  ".join(b.strip() for b in buttons) if buttons else "  # TODO: nessun bottone rilevato"

    return dedent(f"""\
        # {provider_id}.yaml — selettori Selenium per {provider_id}
        #
        # Generato automaticamente da extract.py.
        # Aggiorna i selettori con: ./playwright/record.sh {provider_id}
        # poi riesegui: python playwright/extract.py <recorded_file> --provider {provider_id}
        #
        # Modifica solo questo file quando il sito cambia DOM.
        # Priorità selettori: data-testid > aria-label > name > testo visibile > css class

        publish_url: "{publish_url}"

        fields:
          {fields_yaml}

        buttons:
          {buttons_yaml}
        """)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Converti playwright codegen → selectors YAML")
    parser.add_argument("input", help="File .py generato da playwright codegen")
    parser.add_argument("--provider", "-p", help="Nome del provider (es. vinted). Default: ricavato dal nome file")
    parser.add_argument("--url", "-u", help="URL della pagina di pubblicazione (es. https://www.vinted.it/items/new)")
    parser.add_argument("--out", "-o", help="Path output YAML. Default: providers/selectors/<provider>.yaml")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Errore: file non trovato: {input_path}", file=sys.stderr)
        sys.exit(1)

    # provider id
    provider_id = args.provider or re.sub(r'_\d{8}_\d{6}$', '', input_path.stem)

    # output path
    if args.out:
        out_path = Path(args.out)
    else:
        repo_root = Path(__file__).parent.parent
        out_path = repo_root / "hydra-publisher/src-tauri/resources/python/providers/selectors" / f"{provider_id}.yaml"

    # publish url
    source = input_path.read_text(encoding="utf-8")
    publish_url = args.url or ""
    if not publish_url:
        url_m = re.search(r'page\.goto\(["\']([^"\']+)["\']\)', source)
        if url_m:
            publish_url = url_m.group(1)

    actions = _parse_codegen(source)
    if not actions:
        print("Nessuna azione trovata nel file. Hai registrato qualcosa con il form?")
        sys.exit(1)

    yaml_content = _generate_yaml(actions, provider_id, publish_url)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_content, encoding="utf-8")

    print(f"✓ YAML generato: {out_path}")
    print(f"  Azioni rilevate: {len(actions)}")
    print(f"  Controlla i TODO nel file prima di usarlo in produzione.")


if __name__ == "__main__":
    main()
