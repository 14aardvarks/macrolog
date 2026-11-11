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
| admin | app/admin.py, app/config.py, tests/test_admin.py, tests/test_config.py, tests/test_ai_keys.py, tests/conftest.py |
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
- `app/deps.py`: `current_user(request) -> dict` FastAPI dependency returning `{"id", "username", "display_name", "is_admin"}`;
  raises 401 when signed out, when the session version is stale, or when the user is disabled.
  It reads `request.session["uid"]`. Tests override it with `app.dependency_overrides[deps.current_user]`.
  `require_admin` depends on `current_user` and raises 403 unless `is_admin`.
- `app/main.py`: creates the app, adds Starlette SessionMiddleware (secret from env `SECRET_KEY`, cookie `macrolog_session`,
  SameSite=Lax, max_age 90 days, https_only when env `COOKIE_SECURE=1`), calls every module `init(c)` on startup, includes routers
  `auth.router`, `core.router`, `ai.router`, and mounts app/static at `/` (index.html served for unknown non-/api paths).
  Each router already carries its own prefix. Routers must be named `router`.

users table: `id INTEGER PK, username TEXT UNIQUE NOT NULL, display_name TEXT, password_hash TEXT NULL, oidc_sub TEXT NULL, oidc_iss TEXT NULL (UNIQUE index on (coalesce(oidc_iss,''), oidc_sub); an SSO identity is the pair; NULL iss matches the issuer in effect until stamped at the next SSO sign-in),
email TEXT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, session_version INTEGER NOT NULL DEFAULT 0,
is_admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0, use_global_ai INTEGER NOT NULL DEFAULT 1`.
Columns added later are migrated in place by `db.init_shared` (PRAGMA table_info, ALTER TABLE ADD COLUMN).
`session_version` is bumped on password reset, disable and demotion, which ends every existing session of that user.

## Food object (everywhere)

Nutrients are PER LABEL SERVING.
```
{ id?, source: "off"|"fdc"|"custom"|"ai", source_id?, barcode?, name, brand?,
  serving_amount: float,          # the label amount, e.g. 2
  serving_unit: str,              # canonical unit (below) or a count word like "slice", "piece", "cookie"
  serving_g: float|null,          # grams per label serving if known
  serving_ml: float|null,         # millilitres per label serving if known
  label_text: str,                # as printed, e.g. "2 tbsp (30 g)"
  kcal, carbs, protein, fat: float,
  fiber, sugars, saturated_fat: float|null (g), sodium, cholesterol, potassium, calcium, iron: float|null (mg),
  vitamin_d: float|null (mcg) }      # micronutrients: null means unknown, never zero
```
Micronutrients are per label serving like the macros, so unit scaling and estimated flags work the same; core scales them by
`servings` from units.scale (units.scale itself still returns only the macros and fiber). Entries snapshot all of them; entries made
before they existed stay null. Columns are added in place by `core.init` (PRAGMA table_info, ALTER TABLE ADD COLUMN, safe to run twice).
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
Setting `fdc_api_key` via `config.get` (env `FDC_API_KEY`, default DEMO_KEY, empty also means DEMO_KEY), User-Agent "macrolog/0.1". Network errors never raise; return note text such as
"Open Food Facts unreachable". Open Food Facts: `https://world.openfoodfacts.org/api/v2/product/{code}.json`. USDA:
`https://api.nal.usda.gov/fdc/v1/foods/search`. Micronutrients: OFF nutriments `fiber`, `sugars`, `saturated-fat`, `sodium` (else `salt` / 2.5), `cholesterol`, `potassium`, `calcium`,
`iron`, `vitamin-d` (`*_serving`, else `*_100g` scaled; OFF stores grams, converted to mg or mcg). FDC foodNutrients by nutrientId
(fiber 1079, sugars 2000, saturated fat 1258, sodium 1093, cholesterol 1253, potassium 1092, calcium 1087, iron 1089, vitamin D 1114 mcg)
or nutrientNumber, converted by unitName, scaled from 100 g; FDC `labelNutrients` (per label serving) win when present. Missing stays null.
Use the product's own printed serving text (OFF `serving_size`, FDC
`householdServingFullText` + `servingSize`/`servingSizeUnit`) for label_text and unit, not just 100 g.

## auth.py

Local username/password plus OpenID Connect (authentik). Prefix `/api/auth` for JSON and `/auth/oidc` for redirects.
```
GET  /api/auth/config  -> {"local": bool, "oidc": bool, "oidc_name": str, "needs_setup": bool, "first_admin_via_sso": bool}   # needs_setup only when users is empty and local login is on (or SSO is not configured); first_admin_via_sso when users is empty, LOCAL_LOGIN is off and OIDC is configured (setup then 409s and the first SSO sign-in creates the admin; with local login on SSO sign-up is refused until setup is done)
POST /api/auth/login   {"username","password"} -> {"id","username","display_name"}   sets session uid; 401 on failure; basic rate limit
POST /api/auth/logout
GET  /api/auth/me      -> user or 401
POST /api/auth/setup   {"username","password" (8..1024),"display_name"?} -> {"id","username","display_name","is_admin": true}
                       # first-run: only while users is empty (BEGIN IMMEDIATE + re-check), signs the new admin in,
                       # 409 once any user exists, 429 after 10 attempts per address per 15 min, same-origin
POST /api/auth/sso/unlink -> same as /me   # 409 when not linked, when the user has no password, or when local login is off
GET  /auth/oidc/login  -> 302 to authentik (authorization code + PKCE, state, nonce)
GET  /auth/oidc/link   -> requires a session; 302 to authentik in link mode (flow stores uid and session version)
                       # 401/409/403 HTML page when signed out, already linked, or started cross-site (Sec-Fetch-Site)
GET  /auth/oidc/callback -> login mode: validates, finds user by (oidc_iss, oidc_sub), else by verified email, else auto-creates
                       # (unless OIDC_ALLOW_SIGNUP=0), sets session, 302 to next. Link mode: same token checks, then requires the
                       # same still-valid session user, links sub (no email_verified needed), keeps the session, 302 to /#settings;
                       # 409 page when the sub belongs to another user or the user is already linked
```
Settings (read through `config.get` at call time, so the Admin page can change them live; the env names are the fallbacks):
`LOCAL_LOGIN` (default 1), `OIDC_ISSUER` (authentik application URL like https://auth.example.com/application/o/macrolog/),
`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_NAME` (button label), `OIDC_ALLOW_SIGNUP` (default 0), `OIDC_ADMIN_GROUP` (default empty = off), `OIDC_USER_GROUP` (default empty = off), `OIDC_GROUPS_CLAIM` (default `groups`, max 200 chars each).
Group sync: with an admin group set, each SSO sign-in sets `users.is_admin` from membership in the groups claim (ID token, else userinfo; list or string; case sensitive), logged as `sso.group_promoted`/`sso.group_demoted`; the last active admin is never demoted (`sso.group_demote_blocked`); a missing claim changes nothing. Admin PATCH of `is_admin` on SSO linked users answers 409 while the admin group is set. With a user group set, SSO sign-in is refused (403) unless the claim has the user or admin group, a missing claim included, before any user is created; password sign-in is unaffected. Scope is `openid email profile` plus `groups` when either group is set. Environment only: `PUBLIC_URL`
(base for redirect URI `PUBLIC_URL/auth/oidc/callback`), `TRUST_PROXY`.
`GET /api/auth/me` returns `{"id","username","display_name","is_admin","use_global_ai","personal_key_set","sso_linked","has_password"}`. Disabled users are refused
by password login (403 after a correct password) and by OIDC (403 page, no email linking). Discovery via `{issuer}.well-known/openid-configuration`. Users are created in the Admin page (or by first-run setup). The CLI
`python -m app.auth_cli` is an emergency recovery path only: `add-user USERNAME [--name NAME]` (prompts for password, no echo),
`set-password`, `set-email`, `list-users`, `make-admin`, `remove-admin`, `enable-user`, `disable-user`, `unset-config KEY`
(refuses to leave no active admin). Optionally honor `ADMIN_USER`/`ADMIN_PASSWORD` env to create a first admin at startup if no users exist. `bootstrap_admin` marks ADMIN_USER
as admin on every start, and if no admin exists the lowest-id (enabled first) user becomes admin.
Module API used by main.py: `router`, `init(c)` (creates any auth tables, e.g. login attempts), and `bootstrap_admin()` (no args, opens its own db.conn()).
App start command is `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000` (requires env SECRET_KEY).
State-changing routes reject a present non-matching Origin and any `Sec-Fetch-Site: cross-site`.
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
POST /api/favorites/{food_id}   DELETE /api/favorites/{food_id}   # POST also un-hides the food
```
Meal tags (breakfast|lunch|dinner|snack, zero or more) live in `favorite_tags(user_id, food_id, meal)` and `recipe_tags(meal_id, meal)`;
existing favorites and recipes start untagged. Untagged items show under every meal on Add. `recipe_logs` records each recipe log with its meal.
`hidden_foods(user_id, food_id)` hides a food from the user's Recent and Yesterday lists. `foods.created_by` is the creating user.
Logging a favorite (POST /api/entries) or a recipe with a meal adds that tag; tags are never removed automatically; logging un-hides a food.
```
GET  /api/saved -> {"favorites":[{"food","meals"}], "recipes":[meal + "meals","counts"], "foods":[Food + "in_use"]}   # own items; foods = custom/ai foods I created
PUT  /api/favorites/{food_id}/tags {"meals":[...]}   # own favorite only, 404 otherwise, 400 on unknown meal names
POST /api/saved/favorites/{food_id}/remove           # unfavorite + delete tags + hide from Recent/Yesterday; entries unchanged
PATCH /api/meals/{id} {"name"?,"meals"?,"items"?}    # items replaces the list (amounts, units, removals), at least one item
PATCH /api/foods/{id} {name,brand,barcode,label_text,serving_*,kcal,carbs,protein,fat,fiber}   # creator only (403 otherwise);
                                                     # 409 when the food is in any entry or recipe and nutrition or serving changes (rename still allowed)
POST /api/foods/{id}/refresh-nutrients -> {"food","filled":[nutrient...],"message"}
        # looks the food up again (off: source_id, fdc: fdc id via /fdc/v1/food/{id}, custom or ai with a barcode: barcode lookup) and fills ONLY
        # micronutrients that are null, scaled to the stored serving by weight or volume when the source serving differs; never overwrites a value or
        # changes name, calories or macros, so it works on foods already in logs or recipes. Empty filled means the source had no more data.
        # 400 no source id or barcode, 403 custom or ai food of someone else (off and fdc foods are shared), 404, 409 serving cannot be compared,
        # 429 source rate limit (USDA included), 502 source unreachable. lookup.refresh(food) and lookup.refresh_kind(food) do the network part.
GET  /api/foods/missing-nutrients?date=YYYY-MM-DD -> {"ids":[food id...],"total"}
        # my logged foods (that day, or ever without date) with a null micronutrient, a lookup source (lookup.refresh_kind) and that I may refresh
        # (custom or ai foods only when I created them); distinct, oldest food first; 400 on a bad date. The client refreshes them one by one.
DELETE /api/foods/{id}                               # creator only; 409 when in any entry or recipe, or in another user's favorites
```
Quick favorites items also carry `meals` (tags) and `counts` ({meal: times logged}); recipes carry `meals` and `counts` (from recipe_logs).
```
GET/POST /api/meals    POST {"name","items":[{"food_id","amount","unit"}],"meals"?:[...tags],"meal"?: one tag (older)}  -> meal   # meals wins over meal; used by Create Recipe
POST /api/meals/from-meal {"name","day","meal": breakfast|lunch|dinner|snack|null,"entry_ids"}   # a meal group of one day (null = unassigned); my entries only,
        # each of that day and meal; at least one id, else 400; the recipe is tagged with that meal. The Today screen uses only this route (no day level recipe).
POST /api/meals/from-day {"name","day","entry_ids"?}      # legacy API, not used by the app
DELETE /api/meals/{id}
POST /api/meals/{id}/log {"day"?,"meal"?,"items"?:[{"food_id","amount","unit"}]}   # items override amounts, otherwise saved amounts
GET/PUT /api/goals   {"kcal","carb_pct","protein_pct","fat_pct"}  pcts total 100. Default 3000 and 50/30/20 (carbs/protein/fat).
        targets: carbs g = kcal*pct/4, protein same, fat g = kcal*pct/9. Goals are per user.
GET/PUT /api/settings {"start_screen": "today"|"scan"|"search"|"ai", "default_meal": ...}   # per user, validated
GET/PUT /api/settings/display {"show_macros","show_micros","show_split","show_macro_bar","show_table","micros_open": bool, "micros_shown": [nutrient...], "today_view": "list"|"table"}
        # per user, stored in the settings table (micros_hidden comma list). PUT takes any subset, booleans only (today_view is the string list or table), 400 otherwise.
        # today_view is the Today tab's view, column settings.today_view TEXT NOT NULL DEFAULT 'list', added in place by core.init.
        # Defaults: everything shown, micros_open false (the new section starts collapsed), so existing users see no change.
GET/PUT /api/goals/micros  GET -> {"micros": [{"key","label","unit","kind": "goal"|"limit","default","target"}]}
        PUT {"targets": {nutrient: number > 0 and <= 100000}} (any subset). Table micro_targets(user_id, nutrient, target).
        Defaults and kinds (fixed): fiber 28 g, potassium 4700 mg, calcium 1300 mg, iron 18 mg, vitamin D 20 mcg are goals;
        sugars 50 g, saturated fat 20 g, sodium 2300 mg, cholesterol 300 mg are limits.
```
/api/day also returns `"micros": {nutrient: {"total" (sum of entries with data, null when none), "known" (entries with data),
"count" (all entries), "target", "kind", "unit", "percent"}}`. /api/preview and entries carry every micronutrient (null when unknown).
`can_ask_ai` is true when `ai.enabled()` (import lazily: `from . import ai`).

## ai.py (prefix `/api/ai`, requires current_user)

Optional Claude label reader. Key resolution per user: personal key (user_secrets name "anthropic") if set, else the global key
(setting `ai_global_key`, env `ANTHROPIC_API_KEY`) when users.use_global_ai = 1, else disabled.
```
def enabled(user_id=None) -> bool          # no arg: whether a global key is configured
def resolve_key(user_id) -> (source, key)  # source "user" | "global" | None
GET  /api/ai/status -> {"enabled","key_source": "personal"|"global"|null,"used_this_month","cap","remaining","model","price_known",
                        "est_cost_label","cost_this_month","personal_key_set","personal_key_unreadable","can_use_global",
                        "personal_cap","personal_used_this_month"}    # cap/used/remaining/cost refer to the active source (global if none)
PUT  /api/ai/key {"key"?: str, "cap"?: int 1..10000} -> status    # at least one; key 20..512 printable chars, never sent to the API
DELETE /api/ai/key -> status
POST /api/ai/label  multipart: images (1 to 3 files, jpeg/png/webp, each <= 5 MB), optional barcode (text), optional hint (text)
     -> {"draft": Food (no id, source "ai", barcode if given), "warnings": [str], "used_this_month","cap"}   # NOT saved; client confirms via POST /api/foods
```
Calls `POST https://api.anthropic.com/v1/messages` via httpx with headers `x-api-key`, `anthropic-version: 2023-06-01`, model from
setting `ai_model` (env `AI_MODEL`, default `claude-haiku-5-5`), forced tool use with an input_schema returning the Food fields exactly as printed (serving
as printed, per-serving values). The micronutrients other than fiber are optional plain numbers (left out when not printed), because
strict tool schemas allow at most 16 union typed and 24 optional parameters. They are range checked only when present. Request caps per calendar month counted in table ai_usage (user_id, at, input_tokens, output_tokens,
key_source 'global'|'user'): global-key requests against setting `ai_monthly_cap` (env `AI_MONTHLY_REQUEST_CAP`, default 100) for the
household, personal-key requests against user_ai.monthly_cap (default 100) counting only that user's personal usage. Each reservation
is one BEGIN IMMEDIATE transaction. Return 429 with a clear message when reached. Warnings: kcal differs from 4c+4p+9f by
more than 20 percent, missing serving, any value implausible. The reservation is released exactly once on every failure after it is made (timeout,
connection error, upstream error, cancelled request, any exception) via `release_once`; a call that returned keeps its row (tokens recorded, or 0 if recording fails). The API key is never sent to the browser or logged.

## config.py (live settings store)

Table `app_config(key PK, value, secret, updated_at)`. `get(key, default)` resolves DB value, else env var, else default, at call time.
Managed keys (env fallback): local_login (LOCAL_LOGIN), oidc_issuer, oidc_client_id, oidc_client_secret*, oidc_name, oidc_allow_signup,
ai_global_key* (ANTHROPIC_API_KEY), ai_model, ai_monthly_cap (AI_MONTHLY_REQUEST_CAP, 0..100000), ai_price_in_per_mtok,
ai_price_out_per_mtok (0..10000), fdc_api_key*. Starred keys are secrets: Fernet encrypted with a key derived from SECRET_KEY by
HKDF-SHA256 (info `macrolog/secret-store/v1`); never returned, logged or put in exceptions; APIs report `{"set": bool}`. An undecryptable
secret counts as unset (env fallback) and is flagged `unreadable`. Empty string stored = explicitly empty; deleting the row = use env.
Environment only, never stored: SECRET_KEY, DB_PATH, PUBLIC_URL, TRUST_PROXY, COOKIE_SECURE. Also `user_secrets(user_id, name,
value_enc, updated_at)` for personal keys.

## admin.py (prefix `/api/admin`, every route requires `deps.require_admin` and same origin)

Request bodies are parsed by hand (not pydantic) so validation errors never echo passwords or secrets.
```
GET   /users -> {"users": [{id, username, display_name, email, is_admin, disabled, use_global_ai, has_password, sso_linked,
                            personal_key_set, created_at}]}
POST  /users {username, password (8..1024), display_name?, email?, is_admin?} -> user   # 409 if the name exists (case-insensitive)
PATCH /users/{id} {display_name?, email?, is_admin?, disabled?, use_global_ai?, password?, unlink_sso?: true} -> user
      # 400 disabling yourself, or unlinking your own SSO without a password or while local login is off;
      # 409 demoting/disabling the last active admin, or demoting/disabling/unlinking the last SSO-linked admin while local
      # login is off. Password reset, disable, demotion and unlink bump session_version.
GET   /config -> {"settings": {key: {"value"| "set"+"unreadable", "source": "database"|"environment"|"default", "env", "type"}},
                  "environment": {"SECRET_KEY": {"set"}, "DB_PATH", "PUBLIC_URL", "TRUST_PROXY", "COOKIE_SECURE", "note"},
                  "oidc_test": {"issuer","client_id","at","matches_current"}|null, "warnings": [str],
                  "oidc_redirect_uri": "PUBLIC_URL/auth/oidc/callback"|null, "oidc_redirect_uri_warning": str|null,
                  "authentik_checklist": [str]}
                  # secret "set" is false when only the built-in default applies (fdc_api_key DEMO_KEY)
PUT   /config {key: value|null, ...} -> same as GET   # all or nothing; null removes the override; "" clears a secret
POST  /oidc/test {issuer?, client_id?} -> {"ok", "message"}   # discovery + JWKS, 5 s, 1 MB, same-host redirects only
GET   /log -> {"entries": [{id, at, admin_id, admin_username, action, target, detail}]}   # newest 50
```
Lockout: local_login may be false only with issuer and client id set, PUBLIC_URL set, a passed test recorded for exactly those values,
and an active SSO-linked admin. Every write appends to `admin_log` (no secret values); so do first-run setup
(`setup.first_admin`), self link/unlink from Settings (`self.sso_link`, `self.sso_unlink`) and CLI commands (`cli.*`, admin_id null).
`admin_log` is created by `config.init`, and `config.audit(c, actor_id, action, target, detail)` appends to it.

## Frontend (app/static)

Mobile first, one-hand use, also fine on desktop. Plain ES modules, under about 1000 lines of JS total, no libraries.
Screens: Login, Today, Add, Picker, Claude fallback, Settings. Bottom nav: Today, Add, Settings.
- Start screen is a per-user setting (`today`, `scan`, `search`, `ai`) fetched from /api/settings after login. Today = running macros.
- Today: Calorie Split chart, then the Macro Nutrients heading with bars for calories, carbs, protein, fat showing `value / target (percent)`,
  then a Micro Nutrients section (heading with a small arrow button, aria-expanded, open state saved as micros_open) with one thin bar row per
  shown nutrient: `value / target unit`, Goal or Limit, a "N of M foods" note when some entries lack data, limit bars use --over when exceeded.
  Then entries grouped by meal, each removable and tappable to adjust. On very wide screens the micro section sits under the bars in the middle column.
  Each part follows the Display settings.
  A List and Table toggle sits above the entries (js/daytable.js, model in js/tablemodel.js, the view is the per-user Display setting `today_view`, default List; tapping the toggle changes the view and also saves it to that setting, so the toggle and the setting are one choice and localStorage is no longer used). Table shows the same
  /api/day entries (they already carry every micronutrient) with columns Food, Amount, Calories, Carbs, Protein, Fat and the micronutrients chosen in Display (null is "-"), a subtotal row per meal, a Total row and a remove button per row.
  The Food column is pinned (position: sticky) while the table scrolls sideways on phones; on desktop the table takes the full width under the bars.
- Settings has a Display section (switches saved at once, a Today View List or Table choice, chips for which micronutrients show) and micronutrient targets under Daily Goals.
- The food form has a collapsed "More Nutrients" section (details element, open when a draft already has values) for the optional micronutrients.
- The picker shows the shown micronutrients (fiber stays with the macros) under the macros in the same collapsible section; unknown is "-".
- Add: search box, a Scan button (camera starts ONLY after tapping it; uses BarcodeDetector when available, otherwise show a typed barcode
  field with clear text), and three tabs Favorites, Yesterday, Meals. Quick items show last used amount and unit; tapping opens the Picker prefilled.
  Scan screen: Back button top left, no description or Stop button, the Upload a Photo button sits over the bottom center of the camera view (below the message when there is no camera), typed digits below. Leaving the screen always stops every camera track.
  Copy rules: headings and buttons use Title Case (small words a, an, and, of, to, in, on, or, the stay lowercase); full sentences end with a period, fragments, labels and chips do not.
  Typing a barcode of digits also works. Meals tab opens a checklist with amounts adjustable, one Log button.
- Picker: NEVER auto-logs. A vertical scroll-snap wheel for the amount using the unit's `step`, a unit dropdown from `units`
  (label's own unit selected first), live macros from /api/preview (debounced, show "estimated" when flagged), favorite star, meal selector,
  one Log button. Tapping the number lets the user type an exact value.
- Lookup failure: show "Not Found" with two buttons, "Ask Claude" (only if can_ask_ai) and "Enter Manually". Ask Claude suggests photographing the NUTRITION
  LABEL (optionally with the barcode in the same photo), resizes images client side (max 1280 px, JPEG 0.8), uploads, shows the draft in an editable form
  with any warnings, and only saves via POST /api/foods after the user confirms.
- Add: Search, Scan and the Meal selector sit above the Favorites/Yesterday/Recipes tabs and list. Lists show 20 items with a Show More button.
- Saved (Settings, then Saved): Favorites, Recipes and My foods lists with meal tag chips, rename, delete, recipe item editing, Remove From My Lists, and the food form for My foods.
  Refresh Nutrients (js/refresh.js) is a button in the food edit form (shown for every edited food, with a hint when it has no barcode) and in the picker (only when the food can be looked up and has a blank nutrient); it fills the blank boxes and never overwrites. My Foods also has Refresh All Missing, at most 10 foods per tap, one after another, stopping at a rate limit, with a summary of how many were done and how many are left.
  Refresh logged foods (refreshLoggedControl in js/refresh.js): Today has a Refresh Nutrients button under Micro Nutrients (the logged foods of the viewed day, hidden when nothing needs it) and Settings has Refresh All Logged Foods (every food ever logged). Both take ids from /api/foods/missing-nutrients, say how many foods will be checked, run at most 10 per tap one after another, stop at once on a 429 with a rate limit message, skip foods without a source, remember which foods were already checked this visit so tapping again continues, and report foods checked, values filled and foods left. Today repaints after a batch.
  A search box filters all three sections by name (every word must match, case ignored). The Meal filter (All, Breakfast, Lunch, Dinner, Snack, Untagged) uses the tags and applies to Favorites and Recipes only, strictly (an untagged item is not shown under a meal here). Each section shows 20 items with a Show More button. Remove and delete reload in place, so the search and filter stay.
- Create Recipe (Add tab button, js/recipe.js): name, ingredients, meal tags, Save (POST /api/meals). Add Ingredient opens the Add screen in ingredient mode (search, Scan Barcode, Enter Manually, Favorites and Past Foods tabs, no meal choice); a food opens the picker with a Done button, which returns the amount and unit to the draft (the picker's Serving unit works as usual). Tapping a draft ingredient adjusts it the same way, and the x removes it. The draft lives in app state until Save, and Save returns to Add on the Recipes tab.
- Settings: start screen, goals (kcal and split), sign out, Claude status (used/cap), personal Claude key and cap,
  Connect SSO (plain link to /auth/oidc/link, shown when /api/auth/config oidc is true and me.sso_linked is false) and
  Disconnect SSO (POST /api/auth/sso/unlink, shown when linked and has_password). The app opens Settings for `/#settings`.
- First run: when /api/auth/config needs_setup is true, show a setup form (username, display name, password) posting to
  /api/auth/setup instead of the login screen.
- Admin page (only when me.is_admin): Users, Sign-in (OIDC fields, redirect URI with copy button, checklist, Test connection,
  local login toggle), Claude and USDA settings, Log.
- Macro balance bar (util.js `macroBarParts`, chart.js `macroBar`): thin stacked bar of calorie share from carbs, protein and fat (4/4/9 kcal per g)
  using --c-carbs, --c-protein, --c-fat; `role="img"` with aria-label "Carbs 50%, Protein 30%, Fat 20%"; percents sum to 100; no bar when all macros are zero.
  Shown on Today entries, Add list rows and search results, and in the picker (live), unless Display turns it off. The picker also shows the numbers, so color is never the only cue.
- Install and launch: manifest has 192, 512 and maskable 512 PNG icons plus the SVG, background_color and theme_color match the light background; index.html has
  apple-touch-icon (180), apple-mobile-web-app-capable, status bar style and light/dark theme-color. A fixed `#splash` overlay (icon on --bg) fades out when the first
  screen has rendered, with an inline 6 s safety timeout. No iOS apple-touch-startup-image sizes.
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
  HTTPS, fall back to a file input with `accept="image/*"` (no `capture`, so phones offer the photo library as well as the camera) that decodes the still photo, then to typed digits.
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
