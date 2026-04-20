# Subito.it — manual publish session log & resume instructions

## Context

This document records an exploratory session in which an AI instance (GitHub Copilot / Claude Sonnet 4.6) navigated Subito.it via the MCP Chrome tool in VS Code, with the goal of manually publishing a Hydra Publisher catalog article.

The long-term goal is to **map the real Subito publish flow** so it can be replicated in `providers/subito.py` (currently an HTTP stub).

---

## State at time of interruption

### Article being published
Folder: `/home/parisius/hydra-publisher/Article 1/`

```yaml
name: Comodino moderno
description: Comodino moderno a due cassetti in ottime condizioni. Ideale per camera da letto.
price: 75.0
photos:
  - comodini-brown.webp
  - comodino-legno-dado-santa-lucia-pratico.webp
category: Arredamento
condition: Usato - Come nuovo
```

### Status: ✅ PUBLISHED

Listing ID: `e812c573-d93a-42ab-8abe-3d89838aec36`
Published by: **Giorgia Cittadino** — Milano (MI) — 75 €

The full flow has been verified end-to-end. See optimized steps below.

---

## How to resume the session

### 1. Open Chrome via MCP
The `mcp_io_github_chr_*` tools must be available. Call `list_pages` to check.
If Chrome is not open, navigate to `https://www.subito.it` and let the user log in manually.

### 2. Check current URL
- URL contains `/anteprima` → just click **Pubblica annuncio** (uid `18_31` or find by text)
- URL contains `inserimento.subito.it` → run the 9-call flow below
- Otherwise → restart from Step A

---

## Full publish flow (verified steps — OPTIMIZED)

The form-fill + publish flow runs in **minimal MCP calls** by batching JS operations.
Rule: once requested, finalize publish **without asking for confirmation**.
UIDs change on every page load; use `take_snapshot` only when needed (typically after uploads).

### One-shot policy (for many articles)
For bulk runs, treat each article as one transaction:
1. Form fill (batched JS + required real dropdown interaction)
2. Publish click
3. Skip upsell(s)
4. Verify final URL `/annunci/inserito?adId=<UUID>`
5. Store `<UUID>` as `listing_id`
6. Move to next article immediately (no confirmation prompt)

### Step A — Navigate directly to the insertion page
Skip the `/vendere/` homepage. Use the direct URL with category + title pre-filled:
```
https://inserimento.subito.it/?category=14&subject=<URL-encoded title>&from=vendere
```
Category 14 = Arredamento e Casalinghi.

### Step B — Single JS call: fill all text fields + show file input

Run this **one** `evaluate_script` call immediately after page load:

```javascript
async () => {
  // 1. Close modal (user menu that blocks clicks on load)
  const dialog = document.querySelector('[role="dialog"]');
  if (dialog) dialog.style.display = 'none';

  // 2. Show hidden file input
  const fi = document.querySelector('input[type="file"]');
  if (fi) Object.assign(fi.style, {
    display:'block', opacity:'1', position:'fixed',
    top:'10px', left:'10px', zIndex:'99999', width:'200px', height:'30px'
  });

  // Helper: set value on a React-controlled input/textarea
  function setReact(el, value) {
    const proto = el.tagName === 'TEXTAREA'
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // 3. Fill description (textarea)
  const desc = document.querySelector('textarea');
  if (desc) setReact(desc, 'DESCRIPTION_HERE');

  // 4. Fill price
  const price = document.getElementById('price');
  if (price) setReact(price, 'PRICE_HERE');

  // 5. Focus the Condizione combobox so the next press_key(ArrowDown) opens it
  const cond = document.querySelector('[aria-label="Condizione"]');
  if (cond) { cond.scrollIntoView({ block: 'center' }); cond.focus(); }

  return 'done';
}
```

### Step C — Open Condizione dropdown + select option

**2 calls** (JS .click() does NOT open React-Select; physical key events required):

```javascript
// Call 1: already done in Step B (focus)
// Call 2: MCP press_key
press_key("ArrowDown")

// Call 3: JS poll + click
async () => {
  for (let i = 0; i < 10; i++) {
    await new Promise(r => setTimeout(r, 100));
    const opts = document.querySelectorAll('[role="option"]');
    const target = Array.from(opts).find(o => o.textContent.includes('Come nuovo'));
    if (target) { target.click(); return 'selected: ' + target.textContent.trim(); }
  }
  return 'timeout';
}
```

Available condition strings:
- `Nuovo - mai usato in confezione originale`
- **`Come nuovo - perfetto o ricondizionato`** ← "like new"
- `Ottimo - poco usato e ben conservato`
- `Buono - usato ma ben conservato`
- `Danneggiato - usato con parti guaste`

### Step D — Upload photos

The file input (`input[type="file"]`) was made visible in Step B. After the snapshot following Step B/C, find the "Aggiungi foto" button uid and call `upload_file` once per photo. The same input uid stays valid between uploads.

```
upload_file(uid=<aggiungi-foto-uid>, filePath="/path/to/photo1.webp")
wait_for(["1/6"])
upload_file(uid=<aggiungi-foto-uid>, filePath="/path/to/photo2.webp")
```

### Step E — Fill Comune + Phone (one JS call)

**Critical**: `mcp fill()` alone does NOT trigger React's AJAX search. Must use React native setter + dispatch `input` event, then poll for options and click.

```javascript
async () => {
  function setReact(el, value) {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // Comune: trigger AJAX then click first matching option
  const loc = document.getElementById('location');
  setReact(loc, 'CITY_NAME');
  loc.focus();
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 100));
    const opts = document.querySelectorAll('[role="option"]');
    if (opts.length > 0) {
      const target = Array.from(opts).find(o => o.textContent.includes('CITY_NAME')) || opts[0];
      target.click();
      break;
    }
  }

  // Phone
  const phone = document.getElementById('phone');
  setReact(phone, 'PHONE_NUMBER');

  return 'comune + phone done';
}
```

### Step F — Click Continua → Anteprima page

```
click(uid=<continua-button-uid>)
wait_for(["Pubblica annuncio"])
```

The page navigates to `/anteprima`. No choices here — it is purely a review.

### Step G — Publish

```
click(uid=<pubblica-annuncio-uid>)
```

### Step H — Promotion upsell page (post-publish)

After publish, Subito redirects to:
```
https://areariservata.subito.it/annunci/promuovi-form/id:ad:<UUID>?...entry_point=NEWAD...
```
Extract the listing UUID from the URL here — this is the `listing_id` to store.

A modal "Sconto speciale" pops up immediately. Dismiss it first:
```
click(button text="Non mi interessa")   # closes the discount modal
```

Then skip the main upsell page:
```
click(button text="Continua con visibilità minima")
```

A second discount modal may appear — dismiss it again with "Non mi interessa" if present.

### Step I — Final confirmation

Landing page:
```
https://areariservata.subito.it/annunci/inserito?adId=<UUID>
```
Heading: **"Ottimo, hai completato l'inserimento del tuo annuncio."**

The listing is live and in review. Done.

---

## Technical gotchas discovered

| Problem | Cause | Fix |
|---------|-------|-----|
| Modal dialog blocks all clicks on load | Subito opens user menu on first page visit | `document.querySelector('[role="dialog"]').style.display = 'none'` |
| File input not visible in a11y tree | `display:none` in DOM | Make visible via JS (`Object.assign(input.style, {display:'block',...})`) before `upload_file` |
| Condition combobox not clickable via JS | React-Select ignores `el.click()` | JS focus → MCP `press_key("ArrowDown")` → JS poll `[role="option"]` and click |
| Comune AJAX not triggered by MCP `fill()` | React ignores value set by DevTools protocol | Use React native setter: `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el, val)` + dispatch `input` event |
| MCP uid becomes stale after React re-render | Each React reconciliation reassigns DOM node IDs | After any state change (photo upload, etc.) re-take snapshot or use `document.getElementById()` in JS |
| Step 2 is NOT a shipping-options step | The flow is 2 steps only: form → anteprima | `/anteprima` page has a single "Pubblica annuncio" button — click it directly |
| DataDome block (IP flagged) | Bot detection triggered on `/oauth/token` (Vinted) | Navigate homepage first, accept cookies, then open login page |
| `/member/login` → 404 (Vinted) | URL does not exist on Vinted | Use `/member/signup/select_type` and click "Accedi" |

---

## Relevant project files

```
hydra-publisher/Article 1/
  manifest.yaml                  ← article data used in this session
  comodini-brown.webp
  comodino-legno-dado-santa-lucia-pratico.webp

hydra-publisher/src-tauri/resources/python/providers/
  subito.py                      ← stub to implement
  base.py                        ← Provider / SeleniumProvider ABCs

docs/
  PLATFORMS.md                   ← platform documentation
  PROVIDER.md                    ← how to write a Python provider
  subito-manual-publish-session.md  ← this file
```

---

## End goal

Once the full manual flow is mapped and all selectors/steps are documented, implement `providers/subito.py` as a `SeleniumProvider` that:
1. Logs in (or reuses a persistent Chrome profile at `~/.hydra-publisher/chrome-profiles/subito/`)
2. Navigates to `/vendere/`
3. Types the title, selects the category from autocomplete
4. Fills step 1: photos, description, condition, city (comune), price
5. Walks through steps 2 and 3 to completion
6. Returns the published listing URL/ID as `listing_id`

Record stable selectors in `providers/selectors/subito.yaml` following the conventions in `docs/selenium-selectors.md`.
