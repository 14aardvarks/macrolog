# Macrolog spec (v0.1, milestone 1)

Small self-hosted calorie and macro tracker for two household users. Fast to use (pick up, enter, put down),
standalone (works with no Claude), Claude optional. Keep it SMALL. No npm, no bundler, no framework.

Stack: Python 3.12, FastAPI, stdlib sqlite3, httpx. Frontend is plain HTML/CSS/ES modules served from app/static.
Dependencies: the user said use extra libraries freely if they make it work better. Prefer the lean defaults (fastapi, uvicorn, httpx,
itsdangerous, python-multipart, authlib; frontend vanilla JS) but add a well maintained library, Python or vendored JS, whenever it is the more reliable
or more compatible choice (for example a proper barcode decoder, a password hashing library, or a frontend helper). Every added library must be listed in
requirements.txt (or vendored with its license text in app/static/vendor/), pinned with a lower bound, and mentioned in your final report. Tests use pytest
and pytest-asyncio (asyncio_mode=auto). Priority order is works correctly, then compatible, then small.

## File ownership (agents must only edit files they own)

| Owner | Files |
|---|---|
| manager | SPEC.md, app/db.py, app/deps.py, app/main.py, pytest.ini |
| units | app/units.py, tests/test_units.py |
| lookup | app/lookup.py, tests/test_lookup.py |
| auth | app/auth.py, app/auth_cli.py, tests/test_auth.py |
| core | app/core.py, tests/test_core.py |
| ai | app/ai.py, tests/test_ai.py |
| frontend | app/static/* (index.html, style.css, js/*.js, sw.js, manifest.webmanifest, icon.svg), tests/ui/* |
| infra | Dockerfile, docker-compose.yml, .env.example, requirements.txt, README.md, LICENSE, .gitignore |

Siblings are being written at the same time by other agents. Code against the signatures below. In your own tests, stub or
monkeypatch other modules; do not wait for them and do not write their files. Never edit someone else's file; report problems
in your final message instead.

## Shared pieces (written by manager, already present)

- `app/db.py`: `conn()` context manager (sqlite3, row_factory=Row, foreign_keys on, WAL, commits on exit), `init_shared(c)` creates the
  `users` table. Each module exposes `init(c)` that creates its own tables with CREATE TABLE IF NOT EXISTS. DB path from env `DB_PATH`
  (default `data/macrolog.db`), read at call time so tests can monkeypatch it.
- `app/deps.py`: `current_user(request) -> dict` FastAPI dependency returning `{"id", "username", "display_name"}`; raises 401.
  It reads `request.session["uid"]`. Tests override it with `app.dependency_overrides[deps.current_user]`.
- `app/main.py`: creates the app, adds Starlette SessionMiddleware (secret from env `SECRET_KEY`, cookie `macrolog_session`,
  SameSite=Lax, max_age 90 days, https_only when env `COOKIE_SECURE=1`), calls every module `init(c)` on startup, includes routers
  `auth.router`, `core.router`, `ai.router`, and mounts app/static at `/` (index.html served for unknown non-/api paths).
  Each router already carries its own prefix. Routers must be named `router`.

users table: `id INTEGER PK, username TEXT UNIQUE NOT NULL, display_name TEXT, password_hash TEXT NULL, oidc_sub TEXT UNIQUE NULL,
email TEXT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP`.

## Food object (everywhere)

Nutrients are PER LABEL SERVING.
```
{ id?, source: "off"|"fdc"|"custom"|"ai", source_id?, barcode?, name, brand?,
  serving_amount: float,          # the label amount, e.g. 2
  serving_unit: str,              # canonical unit (below) or a count word like "slice", "piece", "cookie"
  serving_g: float|null,          # grams per label serving if known
  serving_ml: float|null,         # millilitres per label serving if known
  label_text: str,                # as printed, e.g. "2 tbsp (30 g)"
  kcal, carbs, protein, fat, fiber: float (fiber may be null) }
```
Canonical units: mass `g kg oz lb`; volume `ml l floz cup tbsp tsp`; anything else is a count word (lowercase singular).

## units.py (pure functions, no I/O)

```
parse_unit(text) -> str                      # "Tbsp." -> "tbsp", "fl oz" -> "floz", "grams" -> "g", "slices" -> "slice"
available_units(food) -> list[dict]          # [{"unit","label","step","default_amount","estimated"}], FIRST entry is the label's own unit
                                             # with default_amount = serving_amount. Then g, oz, and any other units reachable.
servings_for(food, amount, unit) -> {"servings": float, "estimated": bool}
scale(food, amount, unit) -> {"servings","estimated","kcal","carbs","protein","fat","fiber"}   # fiber may be None
```
Conversion rules: same-family conversions are exact (US customary: 1 cup = 236.588 ml, 1 tbsp = 14.7868 ml, 1 tsp = 4.92892 ml,
1 floz = 29.5735 ml, 1 oz = 28.3495 g, 1 lb = 453.592 g). Mass to volume uses density derived from the food's own
serving_g and serving_ml when both exist. If the label has only one of them, the missing family is reachable only as an
ESTIMATE using 1 g per ml and `estimated: true`. Count units (slice, piece) convert only through serving_g (or equal the label
serving when the label unit is that count word). If a unit cannot be reached at all, omit it from available_units and raise
ValueError from servings_for. "Convert anything necessary" means: whatever the user picks that is reachable, convert.
Steps: g 5, kg 0.05, oz 0.25, lb 0.05, ml 5, l 0.05, floz 0.5, cup 0.125, tbsp 0.5, tsp 0.25, count 0.5.

## lookup.py (network, async)

```
normalize_barcode(raw) -> {"candidates": [12/13/14-digit strings], "valid": bool, "note": str}   # GS1 check digit, 11-digit gets check digit added
parse_serving(text, serving_g=None, serving_ml=None) -> {"serving_amount","serving_unit","serving_g","serving_ml","label_text"}
async barcode(raw) -> {"food": Food|None, "note": str, "valid": bool}      # Open Food Facts then USDA FDC (branded, match gtinUpc)
async search(query, limit=8) -> list[Food]                                   # USDA FDC text search
```
Env: `FDC_API_KEY` (default DEMO_KEY), User-Agent "macrolog/0.1". Network errors never raise; return note text such as
"Open Food Facts unreachable". Open Food Facts: `https://world.openfoodfacts.org/api/v2/product/{code}.json`. USDA:
`https://api.nal.usda.gov/fdc/v1/foods/search`. Use the product's own printed serving text (OFF `serving_size`, FDC
`householdServingFullText` + `servingSize`/`servingSizeUnit`) for label_text and unit, not just 100 g.

## auth.py

Local username/password plus OpenID Connect (authentik). Prefix `/api/auth` for JSON and `/auth/oidc` for redirects.
```
GET  /api/auth/config  -> {"local": bool, "oidc": bool, "oidc_name": str}
POST /api/auth/login   {"username","password"} -> {"id","username","display_name"}   sets session uid; 401 on failure; basic rate limit
POST /api/auth/logout
GET  /api/auth/me      -> user or 401
GET  /auth/oidc/login  -> 302 to authentik (authorization code + PKCE, state, nonce)
GET  /auth/oidc/callback -> validates, finds user by oidc_sub, else by verified email, else auto-creates (unless OIDC_ALLOW_SIGNUP=0), sets session, 302 to /
```
Env: `LOCAL_LOGIN` (default 1), `OIDC_ISSUER` (authentik application URL like https://auth.example.com/application/o/macrolog/),
`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_NAME` (button label), `OIDC_ALLOW_SIGNUP` (default 1), `PUBLIC_URL` (base for redirect URI
`PUBLIC_URL/auth/oidc/callback`). Discovery via `{issuer}.well-known/openid-configuration`. Local users are created by CLI
`python -m app.auth_cli add-user USERNAME [--name NAME]` (prompts for password, no echo) and `set-password`, `list-users`.
Also honor `ADMIN_USER`/`ADMIN_PASSWORD` env to create a first user at startup if no users exist.
Module API used by main.py: `router`, `init(c)` (creates any auth tables, e.g. login attempts), and `bootstrap_admin()` (no args, opens its own db.conn()).
App start command is `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000` (requires env SECRET_KEY).
Must be secure: constant-time compare, scrypt with per-user salt, session fixation safe (clear session on login), validate id_token
signature/iss/aud/exp/nonce, redirect only to same-origin paths.

## core.py (prefix `/api`, all routes require `deps.current_user`)

Tables: foods(shared by both users), entries, favorites, last_used, meals, meal_items, goals, settings.
entries snapshot name and macros at log time. `amount` and `unit` are what the user picked; `servings` is computed with units.scale.
```
GET  /api/foods/barcode/{code} -> {"food": Food|None, "note","valid","can_ask_ai": bool}   # local cache by barcode first, then lookup.barcode, save found food
GET  /api/foods/search?q=      -> {"results": [Food...]}   # order: user's favorites, local foods matching, then lookup.search; every result saved/cached and has id
POST /api/foods                -> Food    # create custom or AI-confirmed food (source "custom" or "ai"); validates numbers >= 0
GET  /api/foods/{id}           -> Food + {"units": units.available_units(food), "last": {"amount","unit"}|null, "favorite": bool}
POST /api/entries   {food_id, amount, unit, day?, meal?} -> entry     # meal in breakfast|lunch|dinner|snack|null; updates last_used
PATCH /api/entries/{id} {amount?, unit?, meal?}   DELETE /api/entries/{id}   # only own entries
GET  /api/preview?food_id=&amount=&unit=  -> units.scale result        # live macros while scrolling the picker
GET  /api/day?day=YYYY-MM-DD -> {"day","entries":[...],"totals","targets","percent","remaining"}   # day defaults to today (server local date; accept ?tz offset optional)
GET  /api/quick/favorites | /api/quick/yesterday | /api/quick/recent -> {"items":[{"food": Food, "amount","unit","servings","kcal","protein"}]}  # amount/unit = last used
POST /api/favorites/{food_id}   DELETE /api/favorites/{food_id}
GET/POST /api/meals    POST {"name","items":[{"food_id","amount","unit"}]}  -> meal
POST /api/meals/from-day {"name","day","entry_ids"?}      DELETE /api/meals/{id}
POST /api/meals/{id}/log {"day"?,"meal"?,"items"?:[{"food_id","amount","unit"}]}   # items override amounts, otherwise saved amounts
GET/PUT /api/goals   {"kcal","carb_pct","protein_pct","fat_pct"}  pcts total 100. Default 3000 and 50/30/20 (carbs/protein/fat).
        targets: carbs g = kcal*pct/4, protein same, fat g = kcal*pct/9. Goals are per user.
GET/PUT /api/settings {"start_screen": "today"|"scan"|"search"|"ai", "default_meal": ...}   # per user, validated
```
`can_ask_ai` is true when `ai.enabled()` (import lazily: `from . import ai`).

## ai.py (prefix `/api/ai`, requires current_user)

Optional Claude label reader, off unless `ANTHROPIC_API_KEY` is set.
```
def enabled() -> bool
GET  /api/ai/status -> {"enabled","used_this_month","cap","model"}
POST /api/ai/label  multipart: images (1 to 3 files, jpeg/png/webp, each <= 5 MB), optional barcode (text), optional hint (text)
     -> {"draft": Food (no id, source "ai", barcode if given), "warnings": [str], "used_this_month","cap"}   # NOT saved; client confirms via POST /api/foods
```
Calls `POST https://api.anthropic.com/v1/messages` via httpx with headers `x-api-key`, `anthropic-version: 2023-06-01`, model from
`AI_MODEL` (default `claude-haiku-5-5`), forced tool use with an input_schema returning the Food fields exactly as printed (serving
as printed, per-serving values). Request cap per calendar month from `AI_MONTHLY_REQUEST_CAP` (default 100) counted in table ai_usage
(user_id, at, input_tokens, output_tokens); return 429 with a clear message when reached. Warnings: kcal differs from 4c+4p+9f by
more than 20 percent, missing serving, any value implausible. The API key is never sent to the browser or logged.

## Frontend (app/static)

Mobile first, one-hand use, also fine on desktop. Plain ES modules, under about 1000 lines of JS total, no libraries.
Screens: Login, Today, Add, Picker, Claude fallback, Settings. Bottom nav: Today, Add, Settings.
- Start screen is a per-user setting (`today`, `scan`, `search`, `ai`) fetched from /api/settings after login. Today = running macros.
- Today: bars for calories, carbs, protein, fat showing `value / target (percent)`, then entries grouped by meal, each removable and tappable to adjust.
- Add: search box, a Scan button (camera starts ONLY after tapping it; uses BarcodeDetector when available, otherwise show a typed barcode
  field with clear text), and three tabs Favorites, Yesterday, Meals. Quick items show last used amount and unit; tapping opens the Picker prefilled.
  Typing a barcode of digits also works. Meals tab opens a checklist with amounts adjustable, one Log button.
- Picker: NEVER auto-logs. A vertical scroll-snap wheel for the amount using the unit's `step`, a unit dropdown from `units`
  (label's own unit selected first), live macros from /api/preview (debounced, show "estimated" when flagged), favorite star, meal selector,
  one Log button. Tapping the number lets the user type an exact value.
- Lookup failure: show "Not found" with two buttons, "Ask Claude" (only if can_ask_ai) and "Enter manually". Ask Claude suggests photographing the NUTRITION
  LABEL (optionally with the barcode in the same photo), resizes images client side (max 1280 px, JPEG 0.8), uploads, shows the draft in an editable form
  with any warnings, and only saves via POST /api/foods after the user confirms.
- Settings: start screen, goals (kcal and split), sign out, Claude status (used/cap).
- Light and dark via prefers-color-scheme. Large tap targets, no confirmation dialogs except destructive deletes of meals. Escape all
  text with textContent, never innerHTML with data. Register sw.js to cache only the static shell.
- Do not ship a mock server. Test pure helpers (picker math, number formatting, day grouping) with node scripts in tests/ui,
  run with `node --test tests/ui`. Keep those helpers in their own module (js/util.js) so node can import them.

## Compatibility (firm requirement, added by the user)

Maximize compatibility. Every feature needs a working fallback, and nothing may be hidden behind a single browser.
- Browsers: current and previous major versions of Chrome, Edge, Firefox, and Safari on macOS and iOS 15 and later, Android Chrome and Firefox.
  JavaScript is ES2020 at most (no top-level await, no `.at()`, no `structuredClone`, no `crypto.randomUUID`). CSS avoids `:has()`, container queries and
  other new features unless a fallback exists (use `vh` before `dvh`, safe-area insets for notched phones).
- Feature detect and degrade: service worker and manifest are optional enhancements; app works without them.
- Barcode scanning: use `BarcodeDetector` when present. Where it is missing (iOS Safari, Firefox) lazily load a vendored decoder from app/static/vendor/
  (a small minified third party barcode decoder file with its license text, loaded only when needed, no npm). If the camera is blocked or the page is not
  HTTPS, fall back to a file input with `accept="image/*" capture="environment"` that decodes the still photo, then to typed digits.
- Input: the picker wheel must work with touch, mouse wheel, and keyboard (arrow keys), plus a typed value. Accept both "," and "." as the decimal separator
  (`inputmode="decimal"`). Respect prefers-reduced-motion. Labels and focus states for screen readers and keyboard users.
- Photos for Claude: always re-encode through a canvas to JPEG before upload so HEIC and large phone photos work everywhere.
- Dates: the client always sends its own local date as `day` (YYYY-MM-DD) on every call that needs one, so time zones never put an entry on the wrong day.
  The server default (its local date) is only a fallback.
- Server and deployment: Docker image must build on amd64 and arm64 (no platform-specific wheels beyond what pip provides, no compiled extras).
  Python 3.10 or newer syntax compatibility is preferred (use `from __future__ import annotations`). SQLite data directory must be a local disk
  (note in README that network filesystems such as NFS can corrupt SQLite WAL files).

## Quality bar

Every module ships with tests that run offline in under 10 seconds. No secrets in code. No print debugging. Clear error messages. Keep functions short.
