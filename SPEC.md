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
  vitamin_d: float|null (mcg),       # micronutrients: null means unknown, never zero
  kcal_estimated: bool }             # kcal was worked out from the macros, see Estimated calories
```
Estimated calories (one place on the server, `units.estimate_kcal` and `units.resolve_kcal`): kcal = 4*protein + 4*max(carbs - fiber, 0) + 2*fiber + 9*fat
per the same basis. `resolve_kcal(kcal, carbs, protein, fat, fiber)` returns (kcal, estimated): a positive value always wins; None, or 0 beside
macros worth at least KCAL_ZERO_FLOOR (5) kcal, becomes the estimate with estimated true; 0 beside zero or tiny macros stays a real 0, and
no energy and no macros stays None (the lookup returns no food). Lookup: OFF tries energy-kcal_serving, energy-kcal_100g, energy-kj and energy
(kJ divided by 4.184, serving then 100 g) and takes the first positive one (a 0 never hides a kJ value), then falls back to the estimate;
FDC also reads kJ (nutrient 268) and accepts a hit with macros but no energy. Storage: foods.kcal_estimated and entries.kcal_estimated
(INTEGER NOT NULL DEFAULT 0, added by core.init, nothing rewritten). `food_dict` and `entry_dict` apply resolve_kcal at read time to foods and
entries from off and fdc whose flag is 0, so older rows with kcal 0 beside macros read as estimated (the stored row stays as it was);
log_entry and macros() carry the flag (macros() returns kcal_estimated, recipe items, recipes (kcal_estimated: any counted row) and
/api/day entries too; a recipe log is estimated when any part is), and /api/day totals sum the resolved values. normalize_food accepts blank
calories (estimate, flagged) and honors a client kcal_estimated only for off and fdc foods; PATCH /api/foods works the flag out itself: a typed
calorie value (even 0) clears it, the shown estimate sent back unchanged keeps it and is worked out again from the macros. Refresh Nutrients
also fills kcal (key "kcal" in filled) when the food is estimated and the source has a real value at a comparable serving, and
GET /api/foods/missing-nutrients lists foods with estimated calories. Client: util.js `kcalEstimated(x)` and KCAL_ESTIMATE_CUE, dom.js
`kcalCue(x)` (a small muted "Estimated From Macros" span) in foodRow (Add lists, Today rows, quick lists), the Today table food cell, Saved
my foods, the picker (a fixed height line under the calories, live from /api/preview), the food form (hidden once Calories is edited),
recipe ingredient lines and recipe log parts.
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
default_pick(food) -> (amount, unit)         # where the picker starts for a food not logged yet: the package's own serving, see below
density(food) -> g per ml|None               # typical density by name keywords (GRAMS_PER_CUP), None when no keyword matches
grams(food, amount, unit) -> float|None      # grams (0.1) when the weight is known exactly; None for estimates, unknown or unit g
match_amount(food, amount, unit) -> {"amount","unit","check","estimated"?: true}|None   # Match Ingredients: amount from a recipe line, see below
```
match_amount (same rule as util.js `matchAmount` on the client): None when the line has no amount. The line's own unit when the
food reaches it at all, as the picker offers it: same unit, weight to weight, volume to volume, weight and volume through the food's own
serving_g and serving_ml, or the label's count word. A unit reachable only through the 1 g per ml estimate (a cup of a food known only by
weight) is used too and the result adds "estimated": true; the row shows a muted "Estimated Conversion" tag (item.estimated from the server)
and counts in the totals, with the same math as the picker. A plain count (no unit, piece, each, whole, large...) uses the label's count word,
else label servings. A typed unit that is not a known measure (can, clove, pinch, to taste) keeps its word, counts like count and never needs a check. Only a
known measure the food cannot reach at all (a cup of a food with no weight and no volume) gives one label serving with check true.
Conversion rules: same-family conversions are exact (US customary: 1 cup = 236.588 ml, 1 tbsp = 14.7868 ml, 1 tsp = 4.92892 ml,
1 floz = 29.5735 ml, 1 oz = 28.3495 g, 1 lb = 453.592 g). Mass to volume uses density derived from the food's own
serving_g and serving_ml when both exist. If the label has only one of them, the missing family is reachable only as an
ESTIMATE and `estimated: true`: with the typical density of the food when its name matches the keyword table `units.GRAMS_PER_CUP`
(about 30 common ingredients, grams per US cup: all purpose flour 125, bread flour 127, whole wheat flour 120, granulated sugar 200, brown sugar packed 213,
powdered sugar 120, butter 227, honey 340, milk 245, water 237, rolled oats 90, uncooked rice 185, cocoa powder 85, salt 288, baking powder 192 and so on;
rounded typical values from USDA household measures and common ingredient weight charts, matched by name regex with words that rule a name out, first match wins),
else 1 g per ml. The table is used only for the missing family: a food's own serving_ml (or serving_g) always wins and is exact. The conversion stays marked
estimated (the "Estimated Conversion" tag stays), it is just much closer. The same density turns a volume label with no grams into grams. The server is the
source of truth: the client converts through the `units` list from GET /api/foods/{id} and has no density table. Count units (slice, piece) convert only through serving_g (or equal the label
serving when the label unit is that count word). If a unit cannot be reached at all, omit it from available_units and raise
ValueError from servings_for. "Convert anything necessary" means: whatever the user picks that is reachable, convert.
Default amount: default_pick is the label's own serving_amount and serving_unit (30 g, 1 cup, 2 slice). Only when the label unit is just "serving"
(or %) and the label gives serving_g or serving_ml does it start on that weight or volume (1 serving of 30 g starts at 30 g). "serving" and "pct"
stay in available_units. GET /api/foods/{id} returns it as `default` {"amount","unit"}; quick items use it when the food was never logged. A prior amount
(last_used) wins while the "Start from my last entry" setting (use_last) is on; the setting off means the package serving.
Steps: g 5, kg 0.05, oz 0.25, lb 0.05, ml 5, l 0.05, floz 0.5, cup 0.125, tbsp 0.5, tsp 0.25, count 0.5.

## lookup.py (network, async)

```
normalize_barcode(raw) -> {"candidates": [12/13/14-digit strings], "valid": bool, "note": str}   # GS1 check digit, 11-digit gets check digit added
parse_serving(text, serving_g=None, serving_ml=None) -> {"serving_amount","serving_unit","serving_g","serving_ml","label_text"}
async barcode(raw) -> {"food": Food|None, "note": str, "valid": bool}      # Open Food Facts then USDA FDC (branded, match gtinUpc)
async search(query, limit=8) -> list[Food]                                   # USDA FDC text search
async search_off(query, limit=8) -> list[Food]                               # Open Food Facts text search (cgi/search.pl, json=1), [] on trouble
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
GET  /api/foods/search?q=&remote=&source= -> {"results": [Food...]}   # order: user's favorites, local foods matching, then remote; every result saved/cached and has id
        # source all (default): local foods of any source, remote = lookup.search (USDA) then lookup.search_off (both at once);
        # off or fdc: favorites, local foods and remote results of that source only; anything else 400. remote=0 skips the network.
POST /api/foods                -> Food    # create custom or AI-confirmed food (source "custom" or "ai"); validates numbers >= 0
GET  /api/foods/{id}           -> Food + {"units": units.available_units(food), "last": {"amount","unit"}|null, "favorite": bool}
POST /api/entries   {food_id, amount, unit, day?, meal?} -> entry     # meal in breakfast|lunch|dinner|snack|dessert|null; updates last_used
PATCH /api/entries/{id} {amount?, unit?, meal?}   DELETE /api/entries/{id}   # only own entries
GET  /api/preview?food_id=&amount=&unit=  -> units.scale result        # live macros while scrolling the picker
GET  /api/day?day=YYYY-MM-DD -> {"day","entries":[...],"totals","targets","percent","remaining"}   # day defaults to today (server local date; accept ?tz offset optional)
        # entries: plain entries (kind "food") and one item per recipe log (kind "recipe"), see "Recipe Logs on Today" below
GET  /api/quick/favorites | /api/quick/yesterday | /api/quick/recent -> {"items":[{"food": Food, "amount","unit","servings","kcal","protein"}]}  # amount/unit = last used, else the package serving (units.default_pick)
GET  /api/quick/recent?meal=breakfast|lunch|dinner|snack|dessert|all   # Past Foods (the Add ingredient finder). With a meal: foods the user logged as that meal
        # (an entry of that food with that meal) plus foods never logged with any meal (untagged, shown under every meal like untagged favorites), newest first,
        # filtered before the limit of 20. No meal or all keeps everything; anything else is 400. Items also carry `meals` (meals it was logged as) and `counts`.
POST /api/favorites/{food_id}   DELETE /api/favorites/{food_id}   # POST also un-hides the food
```
Meal tags (breakfast|lunch|dinner|snack|dessert, zero or more) live in `favorite_tags(user_id, food_id, meal)` and `recipe_tags(meal_id, meal)`;
existing favorites and recipes start untagged. Untagged items show under every meal on Add. `recipe_logs` records each recipe log with its meal.
`hidden_foods(user_id, food_id)` hides a food from the user's Recent and Yesterday lists (Remove From My Lists). Deleting a food is separate, see DELETE /api/foods/{id}. `foods.created_by` is the creating user.
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
GET  /api/foods/missing-nutrients?date=YYYY-MM-DD&claude=1 -> {"ids":[food id...],"total"}   # claude=1: see Full Claude Use
        # my logged foods (that day, or ever without date) with a null micronutrient, a lookup source (lookup.refresh_kind) and that I may refresh
        # (custom or ai foods only when I created them); distinct, oldest food first; 400 on a bad date. The client refreshes them one by one.
DELETE /api/foods/{id} -> {"deleted": id, "everyone": bool}   # soft delete, never a 409: any food, including one in a log entry or a recipe
        # The food is hidden, not removed (foods.deleted INTEGER NOT NULL DEFAULT 0 and table deleted_foods(user_id, food_id), added in place by core.init).
        # It disappears from my search, favorites (and their tags), Recent, Yesterday, picker lists and Saved (favorites and My Foods).
        # Existing entries and recipe rows keep pointing at it, so names, nutrition, totals and recipe logging never change; GET /api/foods/{id} still answers.
        # Scope: a shared Open Food Facts or USDA food, or anyone else's food, is hidden for me only (deleted_foods). A custom or Claude food I created is
        # hidden for everyone (foods.deleted=1, everyone true) only when no other user has it in favorites, entries or recipes; otherwise for me only.
        # Undelete: logging it, favoriting it, scanning its barcode again, or picking it again for a recipe row brings it back as a normal food (my
        # deleted_foods row removed and foods.deleted cleared). A remote search that finds it again lists it, and it returns once picked.
        # The lock stays on editing nutrition or serving of a logged food (PATCH 409), not on deleting.
```
Recipe ingredients (meal_items) may be unmatched: food_id, amount and unit are null and src_text, src_amount, src_unit, src_name,
src_note keep the imported line; skipped rows count for nothing. Databases with the old NOT NULL food_id are rebuilt once in one
transaction by core.init (ids and positions kept). meals.servings (REAL, null = 1) is how many servings the recipe makes.
Total yield: meals.yield_amount (REAL) and meals.yield_unit (TEXT), both null = not set, added in place by core.init. The unit is a
weight or volume unit (core.YIELD_UNITS: g kg oz lb ml l floz cup tbsp tsp), the amount above 0 and at most 1000000. Each meal carries
`yield` ({"amount","unit"} or null), `portions` ([{"unit","label","whole"}]: serving (whole = servings), pct (percent of the recipe,
whole = 100, always), and with a yield its unit first, then the other units of the same family converted exactly) and
`ingredient_grams` (the total weight of a complete recipe when every counted row has an exact weight, a weight unit or the food's own
serving_g, else null; the client offers it as Use Total of Ingredients).
Each meal item carries id, src, skipped, matched, check and grams (unmatched rows have food null and null nutrients); each meal carries servings,
totals and per_serving (matched, not skipped rows; a micronutrient is null when no counted row knows it), matched, needed
(rows not skipped), skipped, checks, steps and complete.
Check Amount: meal_items.needs_check (INTEGER NOT NULL DEFAULT 0, added in place) marks a row whose food is attached but whose amount
could not be worked out. Such a row has check true and matched false; it counts for nothing in totals, matched and complete, and is not
logged, until a plain match (food_id, amount, unit without check) confirms it. It never blocks anything. Unmatching clears it.
Matching is optional. Unmatched, skipped and unconfirmed Check Amount rows contribute zero calories, macros and micros, are never logged as
entries, and keep their imported text line (src) in the recipe as a reference line with no nutrition. There is no loggability rule.
Steps: meals.steps (TEXT, a JSON list of strings, null = none, added in place) is the method in order. At most 60 steps of at most
1000 characters; blanks are dropped and whitespace folded (core.clean_steps). Steps are notes only and never touch nutrition or logging.
Quick favorites items also carry `meals` (tags) and `counts` ({meal: times logged}); recipes carry `meals` and `counts` (from recipe_logs).
```
GET/POST /api/meals    POST {"name","items":[{"food_id","amount","unit"}],"meals"?:[...tags],"meal"?: one tag (older),"steps"?:[str]}  -> meal   # meals wins over meal; used by Create Recipe
POST /api/meals/from-meal {"name","day","meal": breakfast|lunch|dinner|snack|dessert|null,"entry_ids"}   # a meal group of one day (null = unassigned); my entries only,
        # each of that day and meal; at least one id, else 400; the recipe is tagged with that meal. The Today screen uses only this route (no day level recipe).
POST /api/meals/from-day {"name","day","entry_ids"?}      # legacy API, not used by the app
DELETE /api/meals/{id}
POST /api/meals/{id}/log {"day"?,"meal"?,"items"?:[{"food_id","amount","unit"}],"amount"?,"unit"?}   # items override amounts, otherwise saved amounts
        # amount and unit (one of the meal's portions units) log that share of the whole recipe: amount / whole, at most 100
        # whole recipes, every saved amount scaled by it (core.recipe_fraction). Without them the whole saved recipe, as before.
        # logs the matched rows only (core.need_matched); unmatched, skipped and Check Amount rows are left out, never a 409.
        # The one refusal is 400 "Match at least one ingredient to log this recipe." when no row is matched
        # Every log is one recipe log (entry_groups row, entries.group_id); with items, amount and unit only name its portion.
        # Answers {"entries": [...], "group": recipe log item}
POST /api/meals/import {"name","servings"?: number 0..1000,"meals"?,"steps"?:[str],"ingredients":[{"text"?,"amount"?,"unit"?,"name","note"?}]} (1..100) -> meal
        # saves an imported recipe at once with every ingredient unmatched
GET  /api/meals/{id} -> meal
PATCH /api/meals/{id}/items/{item_id} {"food_id","amount","unit","check"?: bool} | {"food_id": null} | {"skipped": bool} -> meal   # match, unmatch, skip
        # check true attaches the food as Check Amount; check needs a food_id; skipped sent with a match is applied after it
PATCH /api/meals/{id}/items {"items":[{"id", ...same body as one row}]} (1..100 rows, each once) -> meal   # all or nothing, used by
        # Accept All and Back on Match Ingredients
DELETE /api/meals/{id}/uncounted -> meal   # Save Without Them: removes every unmatched, skipped and Check Amount row, text lines included;
        # 400 when no row is matched (a recipe needs at least one ingredient). Keep Them to Finish Later calls nothing: the rows stay.
PATCH /api/meals/{id} also takes "servings" (null = 1), "yield" ({"amount","unit"} or null) and "steps" (any time); "items" replaces only the counted rows (matched, not skipped, confirmed); the other rows stay after them as reference lines
GET/PUT /api/goals   {"kcal","carb_pct","protein_pct","fat_pct"}  pcts total 100. Default 3000 and 50/30/20 (carbs/protein/fat).
        targets: carbs g = kcal*pct/4, protein same, fat g = kcal*pct/9. Goals are per user.
GET/PUT /api/settings {"start_screen": "today"|"scan"|"search"|"ai", "default_meal": ..., "use_last", "confirm_ai", "full_claude": bool, "amount_format"}   # per user, validated
        # full_claude is Full Claude Use (column settings.full_claude INTEGER NOT NULL DEFAULT 0, added in place; true or false only, else 400). See "Full Claude Use" below
GET/PUT /api/settings/display {"show_macros","show_micros","show_split","show_macro_bar","show_table","group_recipes","micros_open": bool, "micros_shown": [nutrient...], "today_view": "list"|"table", "search_source": "all"|"off"|"fdc"|"ai", "auto_match": "search"|"claude"|"search_claude"|"off", "recipe_owner": "mine"|"shared"|"all"}
        # per user, stored in the settings table (micros_hidden comma list). PUT takes any subset, booleans only (today_view is the string list or table), 400 otherwise.
        # today_view is the Today tab's view, column settings.today_view TEXT NOT NULL DEFAULT 'list', added in place by core.init.
        # Defaults: everything shown, micros_open false (the new section starts collapsed), so existing users see no change.
        # search_source is the Default Search Source (column settings.search_source TEXT NOT NULL DEFAULT 'all', added in place).
        # auto_match is Auto-Match After Import (column settings.auto_match TEXT NOT NULL DEFAULT 'search', added in place; core.AUTO_MATCHES = search, claude, search_claude, off, a plain TEXT column so new values need no migration;
        # anything else is 400, a bad stored value reads as search). See "Auto-Match After Import" below.
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
                        "personal_cap","personal_used_this_month","server_model","personal_model","personal_price_in",
                        "personal_price_out","personal_cap_default","features": {"label","lookup","recipe": bool}}
                        # cap/used/remaining/cost/model/price_known refer to the active source (global if none)
PUT  /api/ai/key {"key"?: str, "cap"?: int 1..10000, "model"?: str ..100, "price_in"?, "price_out"?: number 0..10000}
     -> status    # at least one; key 20..512 printable chars, never sent to the API; model, price_in, price_out: "" or null clears
     # (validated like the admin ai_model and price settings). Stored in user_ai(model TEXT NOT NULL DEFAULT '', price_in REAL,
     # price_out REAL), columns added in place by ai.init. On the user's own key, requests use the personal model (empty = the
     # server's model, tool choice follows that model) and personal prices for cost and status (empty = no cost, no fallback).
     # Shared key users always get the admin model and prices.
# Feature switches (config, bool, default on): ai_allow_label (AI_ALLOW_LABEL) for /label, ai_allow_lookup (AI_ALLOW_LOOKUP)
# for /lookup (checked after body validation), ai_allow_recipe (AI_ALLOW_RECIPE) for recipe import and Match With Claude.
# Off answers 403 with a clear message before the key, the cap or any request; can_ask_ai is false while label reading is off.
DELETE /api/ai/key -> status
POST /api/ai/label  multipart: images (1 to 3 files, jpeg/png/webp, each <= 5 MB), optional barcode (text), optional hint (text)
     -> {"draft": Food (no id, source "ai", barcode if given), "warnings": [str], "used_this_month","cap"}   # NOT saved; client confirms via POST /api/foods
POST /api/ai/lookup JSON {"text": str 1..200, "note"?: str ..300} -> same reply as /label (barcode null)   # a text description, no images
     # 400 empty, too long, wrong type or unknown keys (checked before the key and the cap); then 503 no key, 429 cap, 502 upstream.
     # Same key resolution, reservation and release_once, usage row, cost fields, strict tool schema and build_draft as /label;
     # the instruction asks for an estimate of one typical serving and wraps the user text in <food>/<note> tags as data, never
     # instructions (angle brackets are stripped). Warnings use estimate wording instead of label wording.
GET  /api/ai/status?chars=N   # est_cost_label is then for a text lookup of N characters (estimate_text_tokens: 650 + N/4 in, 400 out)
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

## recipe_ai.py (prefix `/api/recipes`, requires current_user)

Recipe import and ingredient matching with Claude, through ai._ask (same key resolution, reservation, release_once, usage row
and cost fields as /api/ai/label, one request each, strict tool schemas). Page text, recipe text and ingredient names are data
in tags, never instructions.
```
POST /api/recipes/import/text   {"text": 1..20000 chars, "note"?: ..300} -> {"recipe": {"name","servings","ingredients":[{text,amount,unit,name,note}],"steps":[str]}, "warnings", usage fields}
     # the import tool has one optional property, steps (a plain array of strings): the method only, no ingredient lists, ads or comments;
     # cut to core's limits with a warning
POST /api/recipes/import/photos multipart images (1 to 3, same limits as /label), hint? -> same   # nothing is saved
POST /api/recipes/{meal_id}/match {"item_ids": [1..15 ids of my recipe]} -> {"proposals":[{item_id, kind: candidate|estimate|none,
     food (candidate: saved with id; estimate: source ai draft without id), amount, unit, check, grams, note, warnings, preview}], usage fields}
     # amount and unit: units.match_amount on the recipe line, else on Claude's amount and unit, else one label serving with check true
     # (Accept then sends check, so the row becomes Check Amount)
     # candidates per row: up to 3 local foods, 3 USDA and 3 Open Food Facts results; only a chosen remote candidate is saved.
     # The client applies a proposal only on Accept (POST /api/foods first for an estimate, then PATCH the item).
GET /api/ai/status?recipe_chars=N | recipe_images=N | match_rows=N | micros=N (1..10)   # cost estimates for those requests
     # every status also carries action_costs (Full Claude Use table, see below)
```
A URL source is not built (no server side fetching). It would be one more import route here feeding the text path.

## config.py (live settings store)

Table `app_config(key PK, value, secret, updated_at)`. `get(key, default)` resolves DB value, else env var, else default, at call time.
Managed keys (env fallback): local_login (LOCAL_LOGIN), oidc_issuer, oidc_client_id, oidc_client_secret*, oidc_name, oidc_allow_signup,
ai_global_key* (ANTHROPIC_API_KEY), ai_model, ai_monthly_cap (AI_MONTHLY_REQUEST_CAP, 0..100000), ai_price_in_per_mtok,
ai_price_out_per_mtok (0..10000), ai_allow_label (AI_ALLOW_LABEL), ai_allow_lookup (AI_ALLOW_LOOKUP), ai_allow_recipe
(AI_ALLOW_RECIPE) (bools, default on), fdc_api_key*. Starred keys are secrets: Fernet encrypted with a key derived from SECRET_KEY by
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
Screens: Login, Today, Add, Recipes, Picker, Claude fallback, Settings. Bottom nav: Today, Add, Recipes, Settings.
- Recipes tab (js/recipes.js, helpers in js/recipeimport.js): New Recipe and Import Recipe buttons, then my recipes (and shared ones per the Owner filter, see Shared Recipes) with "3 of 8 matched"
  or "N items - kcal", servings and meal tags. Above the list: a search box (every word of the name must match), a Meal filter chip row (All, Breakfast, Lunch, Dinner, Snack, Dessert, Untagged; strict, same as Saved, via SAVED_FILTERS and filterSavedItems) and a Sort select (Name (A to Z), Newest, Most Used; util.js `sortRecipes`; Newest is the highest id first, Most Used is the total of the per meal `counts` from GET /api/meals). Group Recipes By Meal (Display setting `group_recipes`, default on): the list shows a real heading (h2 class group) per meal tag in the usual meal order with Untagged last, empty groups hidden, a recipe with several tags under each (util.js `groupRecipesByMeal` built on `groupByMeal`, `pageGroups`); the Meal filter limits the groups to that meal and sort applies within each group; off gives the plain list. The list shows 20 rows with Show More. The chosen filter and sort are kept in memory for the session, the search text is not. Every recipe, partial or complete, opens the recipe screen (a partial one keeps its "3 of 8 matched" badge and shows the quiet sentence "5 ingredients are not counted."): Log
  (Meal, Amount and a unit from meal.portions: servings, % of recipe, and the yield units when a yield is set; POST /api/meals/{id}/log
  with amount and unit, so the server scales it), the Ingredients list with Edit Ingredients (opens Match Ingredients with edit true), Meal Tags, Rename, Steps, Serving Size (js/servingsize.js:
  servings, Total yield amount and unit, Use Total of Ingredients when the yield is blank and ingredient_grams is known, which fills it
  in grams and saves at once; Save Serving Size), then a Delete Recipe button (btn danger, last; only on this screen, not on Match Ingredients). It asks "Delete This Recipe?" (saved.js `deleteRecipe`, the same confirm and DELETE /api/meals/{id} as Saved's Delete) and then goes back to the Recipes tab list.
  The log checklist (Add, Recipes sub-tab only; the recipe screen no longer has Adjust Items) has the same Amount and unit at the top; changing them scales every row by
  the same factor, so amounts changed by hand keep their ratio, and switching units keeps the same share of the recipe. New Recipe,
  Import, Match Ingredients and the recipe screen mark the Recipes tab; Save, Save and Continue, Cancel and Back come back to it.
- Start screen is a per-user setting (`today`, `scan`, `search`, `ai`) fetched from /api/settings after login. Today = running macros.
- Today: Calorie Split chart, then the Macro Nutrients heading with bars for calories, carbs, protein, fat showing `value / target (percent)`, each fill colored by percent of goal (see Bar levels below),
- Today quick add: an Add Food button tops the entries column (list and table views) and opens Add. In list view every meal group, empty ones too (util.js `mealGroupsAll`),
  has a row of equal width Add, Scan and Search buttons (aria-labels from `quickLabel`, for example "Add to Lunch") under its entries; the table view has no such row (Add Food covers it). They set `state.quickMeal`, then open Add, Add with `focus` (search box focused), or Scan with autostart. `addMeal()` prefers `quickMeal`, so the Add Meal select, the picker after a barcode lookup (lookup passes it as the picker's meal) and logging use it; it never changes `state.addMeal` and is cleared when Today renders, a bottom tab is tapped or Meal is changed on Add, so the Default Meal behavior of the Add tab is unchanged. Back returns to Today.
  then a Micro Nutrients section (heading with a small arrow button, aria-expanded, open state saved as micros_open) with one thin bar row per
  shown nutrient: `value / target unit`, Goal or Limit, a "N of M foods" note when some entries lack data, limit bars follow Bar levels below; goal bars (fiber, potassium, calcium, iron, vitamin D) stay the normal color because passing a goal is fine.
- Bar levels (util.js `barLevel(pct)` returns `ok`, `near` or `over`; `barState(total, target)` returns `{ level, cue }` from the exact total and target, so display rounding never moves a bar): ok up to and including 75%, near above 75%, over above 100%. Fill classes `.fill.near` (orange, --bar-near) and `.fill.over` (red, --bar-over), each with light and dark values. Color is never the only cue: near shows the text Near Limit and over shows Over, in a `.cue` span next to the amount (colors --cue-near and --cue-over, chosen for text contrast), and the same word is appended to the bar's `aria-valuetext`. No target, or an unknown total (micro dash), gives ok and no cue. Applies to the four macro bars and the limit micro bars, the only goal bars in the app (the table view has none). Protein and the other macros have no limit versus target flag, so all four use the levels.
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
- Add: a Source select (labelled Source, above the search box: All Sources, Open Food Facts, USDA, Claude; util.js `SEARCH_SOURCES`, `searchSources`, `startSource`; Claude is left out while ai_allow_lookup is off;
  it starts at the per user Display setting Default Search Source (All Sources by default), and a change here lasts for the session,
  `searchAction`, `searchHint`) picks where the search box looks and is remembered for the session (state.source). All Sources is the
  Open Food Facts and USDA search and never calls Claude; Open Food Facts or USDA search only that source (local matches included).
  Claude never runs while typing: Search or Enter sends the text (max 200 characters) to POST /api/ai/lookup after confirmClaude
  (opts.chars, so the notice shows the text estimate) and shows one result row with the Claude badge and Estimate; tapping it opens
  the `ai` screen with params.draft, the same editable draft form ("Check What Claude Estimated") that saves through POST /api/foods.
  The last estimate is kept for the session so Back does not ask again. Without Claude for the user, a short hint says so.
  Typed barcode digits and Scan behave the same for every source.
- Add: Search, Scan and the Meal selector sit above the Favorites/Yesterday/Recipes tabs and list. The Recipes list there has the same meal headings when Meal is All and Group Recipes By Meal is on (a chosen meal gives a plain list). Lists show 20 items with a Show More button.
- Amounts (util.js `qtyText`, the one place an amount becomes text; amountText, amountLabel, rowAmountText use it): the per user
  setting amount_format (Settings, Show amounts as) picks fractions or decimals. In fraction mode servings, cooking measures (cup,
  tbsp, tsp, fl oz) and counts (slice, clove, no unit) always round to the nearest friendly fraction, never a decimal (1/8, 1/4, 1/3, 1/2, 2/3, 3/4, whole
  and mixed like 1 1/2; cup, tbsp, tsp and fl oz also get 3/8, 5/8 and 7/8; 0.3125 shows 1/3, 1.34 shows 1 1/3, anything above 0 but under 1/8 shows 1/8,
  never 0; util.js `fractionText`); g, kg, mg, ml, l, oz, lb and percent always show decimals. Decimal mode shows cooking amounts as short decimals (at most 2 places, 1 when close: 0.313 shows 0.3, 1/3 shows 0.33, never 0 for a positive amount; util.js `decimalText`); weights and metric keep their 3 place rounding. Every displayed amount goes through qtyText. Amount boxes show that rounded text but keep the exact number they were filled from: util.js `amountBoxValue` (and `amountMemo` for a live box) returns the exact value while the box text is unchanged from what was shown (0.4 cup shows 3/8 and still saves 0.4), and parses the text only once it is edited (1 1/2, 1/3, 0.4). This covers recipe ingredient amounts on Match Ingredients and import review, serving size and yield, portions on the recipe screen, recipe log and Today, and the picker's typed amount.
  Typing accepts both. Calories, nutrients and recipe servings inputs stay decimal; the food form keeps decimals.
- Cooking View (js/cooking.js, pure helpers `cook*` in js/util.js): a Cooking button on the recipe screen (below Log) opens screen `cooking`
  (params mealId, marks the Recipes tab; Back returns to the recipe). Large text for phone and desktop, light and dark. A servings stepper (minus and
  plus, aria-labels Fewer Servings and More Servings, starts at the recipe's servings, halves under 4 servings and whole servings above, 1000 at most)
  scales the ingredient amounts. Ingredients use the imported wording (src amount, unit, name, note; the amount scales and follows the fraction or decimal
  setting); a line with no amount keeps its text; rows made in the app use the food name and amount. Every row shows, unmatched and skipped ones too.
  Steps are a numbered list. Each ingredient and step is a button with aria-pressed, a box with a check and a line through the text when ticked; ticks live in
  memory only and reset on leaving. `keepAwake` requests a screen Wake Lock when `navigator.wakeLock` exists (feature detected, errors ignored), asks again when the page
  becomes visible, and the screen's cleanup releases it. No API change.
- Today quick buttons: Add (plain) then Scan (primary, green) above the list; the order and layout are unchanged.
- Recipe steps (js/steps.js): the review screen of Import Recipe and New Recipe have a Steps section (a textarea per step with Up,
  Down and Remove, Add Step). The recipe screen shows Ingredients (name, amount and grams) then Steps as a numbered list with Edit
  Steps (or Add Steps), saved by PATCH steps. Split Lines Without Claude leaves steps empty; Save As Recipe from Today starts with none.
- Match Ingredients without the amount screen: Search, Scan Barcode, Enter Manually and Claude lookups still choose the food, but
  picking one does not open the picker. app.js `autoMatch` works out the amount from the recipe line with util.js `matchAmount`, saves
  the match (check true when it could not convert, or when the line has no amount, with one label serving) and returns straight to
  Match Ingredients. Rows show "Food [source] - 1 cup, 125 g - 455 kcal". A Check Amount row has a chip and a small inline amount and
  unit editor (Confirm Amount); matched rows have Edit Amount for the same editor. Check Amount rows count for nothing until confirmed.
- Import Recipe (Recipes tab button next to New Recipe; Read With Claude and Match With Claude hidden while ai_allow_recipe is off, js/recipeflow.js with pure helpers in js/recipeimport.js): step 1 is Paste Text
  (Read With Claude, or Split Lines Without Claude which parses locally and uses no credit) or Photos ("Choose up to 3 photos", toJpeg;
  choosing more keeps the first 3 and says so, the server refuses more than 3), then a review
  screen (name, servings, ingredient rows with amount, unit, name and note, add and remove, Steps, meal tag chips, Save and Continue, Cancel).
  Save and Continue posts /api/meals/import and opens Match Ingredients ("Saved", "Step 2 of 2"): per row the line and its state, Search
  and Scan Barcode (the ingredient finder in ingredient mode; a picked food is matched at once by autoMatch, no picker), Ask Claude,
  Edit Amount or the Check Amount editor, Skip or Unskip; checkboxes, Select All
  and Match Selected; proposals with Accept and Change; once proposals are waiting, Accept N Suggested Matches (primary, above
  Select All) accepts them all in one bulk PATCH (estimates are saved as foods first, kept on the proposal so a retry never saves twice)
  and disappears when none are left; Serving Size (servings, total yield,
  Use Total of Ingredients, saved as each box changes); per serving macros and micronutrients; Back and Save at the bottom.
  There is no Skip All, Next or Done. Matching is optional and nothing forces it. A small link "Jump to Next Unmatched" above the list scrolls
  to and focuses the next unmatched or Check Amount row (hidden when none); "3 of 8 matched" is plain information. Opening the page pre-ticks
  every unmatched row (recipeimport.js unmatchedIds; a return from the food finder keeps the ticks); a row unticks when matched or skipped, and a
  new or unskipped row is ticked. Match Selected is disabled while nothing is ticked, with the label "Tick Ingredients to Match" beside it.
  Saving on Match Ingredients: each row change is still written at once, but only Save counts as a save. A visit (a token kept in the
  match history entry, so a return from the food finder is the same visit) keeps a snapshot of the rows, servings and yield from opening
  (recipeimport.js matchSnapshot). Save goes back (to the Recipes tab, or wherever matching was opened) at once when every row is matched.
  When rows are not matched (unmatched, skipped or Check Amount) it opens an in-page choice, "Save Recipe" ("N ingredients are not matched."):
  Save Without Them (DELETE /api/meals/{id}/uncounted, nothing stored for those rows; with no matched row it only shows "A recipe needs at least
  one ingredient..." and stays), Keep Them to Finish Later (saves, the rows stay as unmatched reference lines with zero nutrition) and Cancel.
  Skip only marks a row; Keep Them keeps skipped rows, Save Without Them removes them. Back (top and bottom)
  leaves at once when nothing changed; otherwise it asks "Discard Changes?" and writes the snapshot back (restoreBody: one bulk PATCH for
  the rows, PATCH servings and yield) before leaving. Leaving by the bottom nav or the browser back keeps the changes. Accepted Claude
  estimates stay as foods. Recipes on the Recipes tab, Add and Saved show "N of M matched" for partial recipes and open and log like complete ones; the recipe screen and the Add checklist add the quiet sentence "N ingredients are not counted.".
- Saved (Settings, then Saved): Favorites, Recipes and My foods lists with meal tag chips, rename, delete, recipe item editing, Remove From My Lists, and the food form for My foods.
  Refresh Nutrients (js/refresh.js) is a button in the food edit form (shown for every edited food, with a hint when it has no barcode) and in the picker (only when the food can be looked up and has a blank nutrient); it fills the blank boxes and never overwrites. My Foods also has Refresh All Missing, at most 10 foods per tap, one after another, stopping at a rate limit, with a summary of how many were done and how many are left.
  Refresh logged foods (refreshLoggedControl in js/refresh.js): Today has a Refresh Nutrients button under Micro Nutrients (the logged foods of the viewed day, hidden when nothing needs it) and Settings has Refresh All Logged Foods (every food ever logged). Both take ids from /api/foods/missing-nutrients, say how many foods will be checked, run at most 10 per tap one after another, stop at once on a 429 with a rate limit message, skip foods without a source, remember which foods were already checked this visit so tapping again continues, and report foods checked, values filled and foods left. Today repaints after a batch.
  A search box filters all three sections by name (every word must match, case ignored). The Meal filter (All, Breakfast, Lunch, Dinner, Snack, Dessert, Untagged) uses the tags and applies to Favorites and Recipes only, strictly (an untagged item is not shown under a meal here). Each section shows 20 items with a Show More button. Remove and delete reload in place, so the search and filter stay.
- Source labels (util.js `sourceLabel`, dom.js `sourceBadge` and `sourceLine`): foods carry `source` (off, fdc, custom, ai), shown as a tiny text badge (Open Food Facts, USDA, Custom, Claude) in the sub line of Add lists and search results, on the Saved rows, under the name in the picker and on the food edit form. Claude foods get a filled badge plus an Estimate word in rows and the note "Values are estimates from Claude." in the picker, the draft form and the Ask Claude screen, which also says it is not a database search. Regular sources get no note. Today shows it too: `/api/day` entries carry `source` (a LEFT JOIN on foods, null when the food row is missing), as a badge in the list row's sub line and under the food name in the pinned Food column of the table.
- New Recipe (Recipes tab button, js/recipe.js, the Create Recipe flow): name, ingredients, meal tags, Save (POST /api/meals). Add Ingredient opens the Add screen in ingredient mode (search, Scan Barcode, Enter Manually, Favorites and Past Foods tabs, no meal choice); a food opens the picker with a Done button, which returns the amount and unit to the draft (the picker's Serving unit works as usual). Tapping a draft ingredient adjusts it the same way, and the x removes it. The draft lives in app state until Save, and Save returns to the Recipes tab. Add has no recipe buttons; its Recipes sub-tab logs recipes.
- Settings: start screen, goals (kcal and split), sign out, Claude status (used/cap), personal Claude key, cap, model and
  input and output prices (Input Price and Output Price, USD per Million Tokens; each hint gives the unit, a sample for the default model
  claude-haiku-5-5 of 0.10 and 0.50 also shown as the placeholder, that cost is not shown unless both prices are set, and a new-tab link
  "Anthropic Pricing Page" to https://platform.claude.com/docs/en/about-claude/pricing; the admin price fields match),
  Connect SSO (plain link to /auth/oidc/link, shown when /api/auth/config oidc is true and me.sso_linked is false) and
  Disconnect SSO (POST /api/auth/sso/unlink, shown when linked and has_password). The app opens Settings for `/#settings` (js/routes.js reads it as `#/settings`).
- First run: when /api/auth/config needs_setup is true, show a setup form (username, display name, password) posting to
  /api/auth/setup instead of the login screen.
- Admin page (only when me.is_admin; every Claude field and the three Allow Claude switches carry a hint with their default): Users, Sign-in (OIDC fields, redirect URI with copy button, checklist, Test connection,
  local login toggle), Claude and USDA settings, Log.
- Macro balance bar (util.js `macroBarParts`, chart.js `macroBar`): thin stacked bar of calorie share from carbs, protein and fat (4/4/9 kcal per g)
  using --c-carbs, --c-protein, --c-fat; `role="img"` with aria-label "Carbs 50%, Protein 30%, Fat 20%"; percents sum to 100; no bar when all macros are zero.
  Shown on Today entries, Add list rows and search results, and in the picker (live), unless Display turns it off. The picker also shows the numbers, so color is never the only cue.
- Install and launch: manifest has 192, 512 and maskable 512 PNG icons plus the SVG, background_color and theme_color match the light background; index.html has
  apple-touch-icon (180), apple-mobile-web-app-capable, status bar style and light/dark theme-color. A fixed `#splash` overlay (icon on --bg) fades out when the first
  screen has rendered, with an inline 6 s safety timeout. No iOS apple-touch-startup-image sizes.
- Light and dark via prefers-color-scheme. Large tap targets, no confirmation dialogs except destructive deletes of meals. Escape all
  text with textContent, never innerHTML with data. Register sw.js to cache only the static shell.
- Meals are one ordered list, five long: Breakfast, Lunch, Dinner, Snack, Dessert (core.MEALS on the server, util.js `MEALS` and `MEAL_LABELS`
  on the client; every selector, chip row, filter, Today group and table subtotal is built from it). Dessert is a full meal after Snack
  but is never chosen by `guessMeal` (time of day); it is only ever picked by hand, as the Default Meal or on the Meal selectors. No table
  has a CHECK on meal (meals are validated in core.MEALS only), so older databases need no migration and take dessert at once
  (tests/test_dessert.py). Untagged favorites and recipes show under every meal, Dessert included. Meal chips wrap on a narrow phone.
- Picker layout never shifts while units or amounts change: the "1 serving = 28 g" line (`.base-line`) always takes one line of height and is
  empty when there is nothing to show (label unit, serving, %), and the Estimated Conversion badge sits in a fixed `.badge-slot` that is
  hidden with visibility, not removed. Both stay on one line (ellipsis), so the unit wheel, kcal and macro block and the Meal and Log
  controls below keep their position for every unit.
- Update banner (js/update.js `watchUpdates`, `updateBanner`, `startUpdates`): sw.js no longer calls skipWaiting while installing; a new worker waits.
  When one is installed and waiting while another controls the page (or a new worker took over by itself), a sticky bar at the top of the app
  reads "Update Available" with a Reload button (role status, light and dark). Reload posts `{type: 'SKIP_WAITING'}` to the waiting worker (sw.js
  answers with skipWaiting), then reloads on controllerchange (with a short timer as a fallback). A fresh install, with no earlier controller,
  shows nothing. The page also asks the registration for a newer worker whenever it becomes visible. Bump the sw.js cache name (now v51) with
  every change to the shell and list new js files in SHELL.
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

## Today Keeps Its Place (v51)

- Removing an entry (X on a row, in List or Table), Remove Recipe on the recipe log screen, changing a portion (picker or recipe log) and Refresh Nutrients
  repaint Today without jumping to the top. Real navigation (a tab, a new screen) still starts at the top with focus on main.
- app.js `holdToday(e)` stores `state.hold` (util.js `todayHold`: scrollY, the row key from `entryKey`, its index, the day). Remove buttons carry `data-row`. `render`
  takes the hold for the next Today render only (same day, and only from Today, the picker or the recipe log), skips the early clear of main so the page keeps its height,
  then `restoreToday` scrolls back and focuses with util.js `holdTarget`: the opened row's own button when it is still there, else the remove button that took the
  removed row's place (the last one when the last row went), else the Today heading when no rows are left. At the very bottom of a page that shrank the browser clamps scrollY.
- The quiet Refresh Nutrients control on Today starts hidden, so the page does not shift when it turns out to be unneeded.

## Recipe Logs on Today (v50)

- A logged recipe is one row on Today. Every ingredient is still its own entry (snapshot nutrients, history, totals, micros,
  goals and Refresh Nutrients unchanged), linked by `entries.group_id` (INTEGER, null = a plain entry, added in place by core.init with
  index entries_group) to one `entry_groups` row: `id, user_id, day, meal, meal_id` (the recipe, no foreign key, so a log outlives a
  deleted recipe), `name` (the recipe name at log time), `amount, unit` (the portion: serving, pct or a yield unit), `fraction` (share
  of the whole recipe) and `portions` (JSON snapshot of meal.portions, so the log rescales even after the recipe changes or is deleted).
  `recipe_logs` (tags and Most Used counts) is unchanged and separate. Entries logged from recipes before v50 have no link and stay
  separate rows; there is no data to group them.
- POST /api/meals/{id}/log creates the group. Without amount the portion is the whole recipe (servings servings); with items (the Add
  checklist) amount and unit, when sent, only name the portion.
- /api/day `entries` holds plain entries (`kind` "food", every entry also carries `group_id`) and, at the place of its first ingredient, one
  item per recipe log: `{"kind": "recipe", "id": null, "group_id", "meal_id", "day", "meal", "name", "brand": null, "food_id": null,
  "source": null, "amount", "unit", "fraction", "servings": null, "portions", "parts": [entries], kcal, carbs, protein, fat (sums, 2 places)
  and every micronutrient (sum of the parts that know it, null when none)}`. totals, percent, remaining and micros (known and count count
  ingredient rows, as before) are computed from the ingredient rows exactly as before.
```
GET    /api/entry-groups/{id} -> recipe log item          # own only, 404 otherwise
PATCH  /api/entry-groups/{id} {amount?, unit?, meal?}      # amount and unit: one of its portions (core.recipe_fraction, at most 100 whole
       # recipes); every row is scaled by new fraction / old fraction and worked out again from its food like PATCH /api/entries
       # (the snapshot is scaled when the food is gone or its unit unreachable). meal moves every row.
DELETE /api/entry-groups/{id} -> {"deleted": id}           # removes every row of the log
POST   /api/entry-groups/{id}/copy {day?, meal?, amount?, unit?} -> recipe log item   # logs it again as a new group (Yesterday on Add);
       # meal defaults to the log's own; counts in recipe_logs and tags the recipe when it still exists and a meal is given
```
  PATCH /api/entries/{id} with another meal takes that row out of its group; deleting the last row of a group deletes the group.
  GET /api/quick/yesterday lists a recipe log once (`kind` "recipe", group_id, meal_id, name, amount, unit, fraction, portions, meal, kcal,
  carbs, protein, fat, parts = row count), ordered with the food items by entry id; its rows are not listed as foods. Past Foods (recent)
  and meal counts still see every ingredient row. POST /api/meals/from-meal takes the ingredient entry ids, so a recipe saved from Today
  holds ingredients, never a recipe inside a recipe.
- Client: recipeimport.js `isRecipeLog`, `recipeAmountText` ("1 serving", "1/2 serving", "25% of the recipe", "250 g"),
  `entryAmountText`, `saveRecipeRows` and `tickedIds` (Save As Recipe: one ticked row per recipe log standing for its parts), `scaledLog`
  (live preview), `REMOVE_RECIPE_CONFIRM` ("Remove This Recipe From Today?"). Today's list row and table row look like an entry with a
  Recipe badge in place of the source; tapping opens js/recipelog.js (`recipelog` screen, params groupId): name, portion and ingredient
  count, combined calories, macros, macro bar and shown micros (live while the amount changes), Change (Amount and Of the recipe unit,
  Meal, Save Changes, one PATCH with what changed), the read only Ingredients (amount, kcal, source) and Remove Recipe. Remove Recipe and the
  row's X ask REMOVE_RECIPE_CONFIRM first and delete the group. Yesterday on Add shows a recipe log as one row; tapping opens the same
  screen with params.copy (heading Log Again, button Log, no Remove, Add tab marked), which posts /copy for today.

## Match With Search, editing on Match Ingredients, Add order (v42)

- Match Selected has a method switch "Match With: Search | Claude" (js/recipeflow.js, helpers in recipeimport.js `MATCH_METHODS`, `matchMethod`,
  `methodBatch`, `matchDoneText`; segmented buttons with aria-pressed, session state ctx.flow.method, default Search; the switch is hidden and
  Search is used when Claude is off or not set up). The button reads Match Selected With Search or With Claude. Checkboxes and Select All show on every
  row that is not skipped, with or without Claude. Claude keeps its confirm dialog, cost and 15 rows per request; Search has no confirm, uses no
  credit and takes up to 40 rows (the rest stay ticked, and the note says so). Ask Claude on a row always uses Claude.
- `POST /api/recipes/{meal_id}/match-search` {"item_ids": 1..40, "source"?: all|off|fdc} -> {"proposals", "method": "search", "rate_limited": bool} (recipe_ai.py). No key,
  feature switch or cap is checked and Claude is never called. Candidates per row: my own foods (favorites, past foods that are not hidden, foods I
  made), then foods saved on the server, USDA and Open Food Facts (top 5 each; source off or fdc restricts all of them, own foods included). Scoring
  (`name_score`, `pick_best`) is word overlap with light singulars; the part of a name before its first comma counts as its own name ("Butter, salted"
  is Butter). Class 2 is the same words, 1 holds every query word, 0 at least half; nothing else is a candidate. Order: class, then my own foods, then
  overlap score, then the shorter name before any comma, then source order (own, server, USDA, Open Food Facts). So "butter" picks Butter over
  Peanut butter, and my own food wins only against an equal class. An exact name among my own foods skips the network; a repeated name is looked up
  once. Proposals have the Claude shape (kind candidate or none, food, amount and unit through units.match_amount on the recipe line, check, grams,
  preview, warnings) plus method "search" and a note ("Same name in USDA", "Closest name in your foods"). No candidate gives kind none with
  "No match found." and nothing is saved; a chosen remote food is saved like Claude's. Accept, Accept N Suggested Matches, Change and Skip work as before;
  the heading reads Suggested Match (Search Result when none).
- Editing: Edit Ingredients on the recipe screen and in Saved opens Match Ingredients with params.edit (same page, a different intro; Back and Save as above).
  Every row has Search, Scan Barcode, Ask Claude, Edit Amount, Skip and Remove (not when one row is left); Add Ingredient takes a typed line
  (split by parseIngredientLine) with Add or Add and Search. `POST /api/meals/{id}/items` {"src"?, "food_id"?, "amount"?, "unit"?, "check"?,
  "skipped"?, "position"?} adds a row (409 past 100) and answers the recipe plus "added"; `DELETE /api/meals/{id}/items/{item_id}` removes one
  (409 for the last). Unmatching a row that has no imported line (a recipe built by hand) keeps the food's name and amount as its line, so it can be
  searched again. The match snapshot keeps each row's line; Back (restoreBody: remove, add with position, items, meal) deletes rows added since, puts
  removed rows back in place and restores the rest. The old checklist (js/app.js mealScreen) is only for logging from Add, Recipes.
- Add screen order, top to bottom: Enter Manually and Scan Barcode (equal width), Search, Source, Meal (not in ingredient mode), the tabs and lists.


## Shared Recipes (v54, issues #18 and #25)

- `meals.shared INTEGER NOT NULL DEFAULT 0` (added in place by core.init), so every existing recipe stays private. `recipe_logs.user_id INTEGER`
  (added in place; null on older rows means the recipe owner) makes Most Used counts per viewer. `settings.recipe_owner TEXT NOT NULL DEFAULT 'mine'`
  (core.RECIPE_OWNERS mine, shared, all; returned and validated by GET/PUT /api/settings/display, anything else 400, a bad stored value reads as mine).
- Read (GET /api/meals/{id}, log, duplicate, Cooking): my recipe or a shared one (core.visible_meal); anyone else's private recipe is 404, admins included.
  Write (PATCH /api/meals/{id} incl. shared, items routes, uncounted, DELETE, and recipe_ai match and match-search): the owner, or an admin for a recipe
  they can read (core.writable_meal); anyone else gets 403 on a shared recipe. own_meal (owner only) remains for new rows of my own.
- `GET /api/meals?owner=mine|shared|all` (default mine, as before; shared = other users' shared recipes). Each meal also carries `shared`, `mine`,
  `can_edit` and `owner` {"id","name"} (display name, else username). `counts` are the viewer's own logs.
- `PATCH /api/meals/{id} {"shared": bool}` (bool only, else 400). `POST /api/meals/{id}/duplicate {"name"?}` copies a readable recipe into a new private
  recipe of mine (every row with its imported line, skipped and Check Amount state, tags, servings, yield, steps; not logs); name defaults to "<name> (Copy)".
- Logging someone else's shared recipe (POST /api/meals/{id}/log, entry-groups copy) writes entries to my log only, counts in recipe_logs with my id
  and never adds tags to their recipe. Foods are one shared table, so the owner's custom foods resolve for everyone. log_entry(revive=False) on
  another owner's recipe clears only my deleted_foods row and never un-deletes the owner's food for everyone. GET /api/saved stays own only.
- Client: util.js `RECIPE_OWNERS`, `RECIPE_OWNER_LABELS`, `recipeOwner`, `filterRecipeOwner`, `ownerText` ("Shared by Ann", "Shared" for my own shared
  one), `ownerEmptyText`, `DEFAULT_DISPLAY.recipe_owner`. The Recipes tab loads GET /api/meals?owner=all and filters with an Owner filter chip row
  (Mine, Shared With Me, All) between search and the Meal filter, saved at once as recipe_owner. Cards show the owner line. The recipe screen shows the
  owner line; with can_edit it adds a Sharing section (switch "Share With Other Users", hint stating it is off by default) and a Duplicate section,
  otherwise only Steps (read only) and Make It Yours with Duplicate. Add, Recipes lists mine and shared (owner in the sub line, delete only on mine).
  Shell cache macrolog-shell-v57 (v57, issue #32: amount boxes keep the exact stored value until edited).

## From Previous Recipe (v64, issue #40)

- `app/ingredients.py`: `words()` (the Search normalizer, lowercase words with light singulars, now shared by recipe_ai `_words`) and `key()`: lowercase, text in
  brackets and after the first comma dropped, numbers, fractions and units (cup, tbsp, g, clove, can ...) and preparation or size words (chopped, fresh, large ...)
  dropped, plural to singular (ies to y, oes, s; ss, us and is endings stay), words sorted. Words that change the food (whole, dried, brown, ground) stay.
- `recipe_ai.previous_matches(user_id, names, exclude_meal, source)` runs one SELECT over meal_items joined to meals and foods (existing meal_items_meal
  index; no schema change): recipes with user_id = me or shared = 1, rows matched (food_id set, not skipped, src_name set), the food not deleted
  (foods.deleted = 0 and not in deleted_foods for me), not the recipe being matched, and f.source = source when the Search source is off or fdc. Names are
  keyed in Python and only the wanted keys kept. Per key the food wins by newest recipe id, then times matched, then newest row id (meal_items has no
  timestamp, so recipe id is the recency). Other users' private recipes are never read. No query when no name has a key.
- match-search: a row with an earlier match gets that food first (kind candidate, note "Matched to this food in an earlier recipe", `from_previous: true`), with no
  network lookup for it, so it is also faster and never rate limited. Other rows search as before.
- POST /api/recipes/{id}/match (Claude): the earlier food becomes candidate 1 for its row (one per row, at most 15), the row block gets `earlier match: [1]`
  and the instruction asks Claude to prefer it. A proposal that ends on that food has `from_previous: true`; when Claude chooses no candidate (null, missing
  row or an estimate) the earlier food is used instead. Claude may still pick another candidate when the line clearly differs.
- Client: Match Ingredients shows the cue "From Previous Recipe" in the proposal head (instead of Database Match), and under Accept N Suggested Matches the
  line "N of these are From Previous Recipe." (`previousCountText`, `PREVIOUS_CUE`). Tests: tests/test_previous_match.py, tests/ui/fullclaude.test.mjs. Shell cache macrolog-shell-v64.

## Auto-Match After Import

- Settings, Display has Auto-Match After Import (select: Search, Claude, Search Then Claude, Off; saved at once like the other Display choices, per user,
  default Search) with a hint that states Search is the default, that Search is free, that the Claude choices use Claude requests (cost shown first when Confirm
  before using Claude is on) and fall back to Search when Claude is not set up, and that Off leaves every ingredient to match. Server: `settings.auto_match`
  (plain TEXT, no CHECK constraint, so the new values need no migration), `core.AUTO_MATCHES` = search, claude, search_claude, off, returned and validated by
  GET/PUT /api/settings/display (anything else is 400, a bad stored value reads as search). Client: util.js `AUTO_MATCHES`, `autoMatch`,
  `DEFAULT_DISPLAY.auto_match`; recipeimport.js `autoMatchOn` (every value except off), `autoMatchPlan(setting, aiOn)`, `autoClaudeBatch`.
- Claude options (same flow as Match Selected With Claude, no new route): `autoRun` computes the plan with aiOn = Claude is set up and the recipe switch is on.
  Search runs Search only. Claude asks Claude about every unmatched row (up to 15, the rest stay ticked). Search Then Claude runs Search first, then asks Claude
  about the unmatched rows that have no food proposal (up to 15; with Full Claude Use about every row not taken from a previous recipe, see Full Claude Use). `confirmClaude` runs first (respects confirm_ai, shows the request count and cost, blocks past the
  monthly cap); Cancel leaves those rows unmatched and ticked with a quiet note, keeping any Search proposals. With Claude not set up or the switch off, Claude and
  Search Then Claude run Search only and add the note "Claude is not available, so Search ran instead." A Claude failure keeps the Search proposals and adds a quiet
  note. Proposals are Claude Suggests like a manual run, never accepted automatically; Accept N Suggested Matches works as before.
- Save and Continue (ctx.flow.saved in app.js) sets a one-shot in memory (`state.autoMatch` = the new meal id) when the setting is Search. Match Ingredients
  takes it once (`ctx.flow.takeAuto`, params.saved only), so reopening a recipe, a return from the food finder, Back and a reload never search again.
  Nothing is stored for it.
- The page renders at once with every unmatched row ticked, then `autoRun` (recipeflow.js) calls POST /api/recipes/{id}/match-search on the unmatched rows
  (recipeimport.js `autoMatchIds`: the same 40 row cap, the Default Search Source or the Source chosen on Add). Status "Finding Matches..." while it runs,
  with Match Selected disabled and the rest of the page usable. The Search setting never asks Claude and uses no credit. Proposals are kept like a manual Search (Suggested
  Match with source badge, amount and unit from units.match_amount, Estimated Conversion or Check Amount where relevant) and "Accept N Suggested Matches"
  appears. `autoMatchResult` drops answers for rows that were matched or skipped while it ran; only rows that got a food are un-ticked, rows without one stay
  ticked for a manual Match Selected. On a failure the rows stay unmatched and ticked and a quiet note says suggestions could not be found (never an error,
  never blocks).
- USDA rate limit: `lookup.search(query, limit, state=None)` sets state["limited"] on a 429. match-search shares one state per request: after a 429 rows
  still waiting skip USDA (checked inside the concurrency gate, so up to SEARCH_CONCURRENCY lookups already in flight may also be refused), they still use
  my foods and Open Food Facts, carry "skipped": true (and "Not searched." when nothing was found) and the response has "rate_limited": true. The page shows the
  quiet note "USDA lookup limit reached. Rows below were not searched." above the rows (`rateLimitNote`), for manual Search runs too, cleared by the next search.

## Screen URLs (v58, issue #22)

- Hash routes, so the server, sw.js and the auth redirects are unchanged. One table in js/routes.js (no DOM, tested in tests/ui/routes.test.mjs):
  `#/today`, `#/today/log/{groupId}` (recipe log), `#/add`, `#/add/food/{foodId}[?meal=]` (picker), `#/add/recipe/{mealId}[?meal=]` (log checklist),
  `#/recipes`, `#/recipes/{id}`, `#/recipes/{id}/cooking`, `#/settings` (also the legacy `#settings`), `#/saved`, `#/admin`. Ids are positive whole numbers.
- Pure helpers: `parseRoute(hash)` (route or null), `formatRoute(name, params)` (hash or null), `routeUrl(name, params, current, inFlow)`,
  `startRoute(hash)` (null for no hash, Today for an unknown route) and `tabOf(name)` (the bottom bar button; it replaces app.js NAV_OF, and
  `params.nav` and the recipe finder rule still win in app.js `navKey`).
- Screens without a URL keep the one they were opened from, so a reload opens that parent: import, review, Match Ingredients, Create Recipe, scan,
  lookup, manual, Claude, edit food, the picker for a logged entry or a recipe row, a recipe log copied from Yesterday, and the food finder and picker while
  they serve a recipe (app.js `inRecipeFlow`). In progress flows never resume mid flow.
- app.js `go` pushes or replaces the history entry with its URL; popstate renders the entry's state as before, and a hash typed by hand (an entry
  without state) opens its route. A reload or sign-in opens the URL (or the Start Screen without one); the entry's own params are kept when they
  format to the same URL (a picker amount), and its depth is kept so Back still walks the entries from before the reload.
- A screen opened from a URL that answers 403 or 404 (another user's or a deleted recipe) opens Today in its place; Admin for a non admin opens Today.
- The URL waiting for sign-in is kept in sessionStorage (`macrolog-route`) so single sign-on, which leaves the page, comes back to it. Sign Out
  clears the URL and that key, so the next sign-in opens the Start Screen.
- Today keeps its place (v51) and the Update Available reload are unchanged; a reload after an update reopens the same screen.

## Full Claude Use (v59, issue #26)

- Per user setting `full_claude` in GET/PUT /api/settings (settings.full_claude, default off, booleans only). Settings, Claude has a checkbox
  Full Claude Use right above the key section (claudekey.js `renderFullClaude`, saved at once) with the hint "Off by default. ..." (`FULL_CLAUDE_HELP`)
  a cost table and a short warning (v61, issue #35: Claude is used on its own, recipe imports and their matching run without asking, costs add up, the monthly request limit applies; `fullClaudeWarning`). Confirm before using Claude stays a separate setting for every other Claude step.
- When on, Claude runs on its own in four places. Each step needs the admin switch named and a usable key, else it is skipped silently; each
  uses the normal reservation and the monthly cap (never exceeded: at the cap nothing is sent and one quiet note says "Monthly Claude limit
  reached, so Claude was not used.", util.js `CLAUDE_CAP_NOTE`); with Confirm before using Claude on the usual notice with the estimated cost
  comes first, with it off it runs quietly (util.js `autoClaudePlan` gives off, cap, confirm or run; notice.js `autoClaude`).
  1. Auto-Match After Import (ai_allow_recipe): util.js `effectiveAutoMatch` turns Search (or an unset or bad value) into Search Then Claude;
     an explicit Claude, Search Then Claude or Off is never changed (a stored explicit "search" is the default and cannot be told from a choice, so it
     is treated as unset). Issue #40: Search Then Claude used to ask Claude only about rows Search left without a proposal, and real USDA and Open Food
     Facts data proposes something for every row, so Claude never ran and nothing said so (the mocks only missed a row or two). Under Full Claude Use
     `autoClaudeBatch(items, props, true)` now asks about every unmatched row except proposals with `from_previous`; `claudeKeep` keeps a Search
     proposal when Claude finds no food for that row. Without Claude the run does Search and always shows a note (`claudeOffNote`: recipe switch off
     "Claude recipe matching is turned off on this server, so Search ran instead.", else "Claude is not set up for you, so Search ran instead."); at
     the cap `CLAUDE_CAP_NOTE`; a failure `AUTO_CLAUDE_FAILED`. A skip is never silent.
  2. A search on Add with no result (remote search, text up to 200 characters, ai_allow_lookup) asks POST /api/ai/lookup for one estimate,
     shown with the Claude badge, Estimate and "Nothing was found in the databases, so this is a Claude Estimate." plus Enter Manually; kept for
     the session (state.fallback) so Back asks nothing again. A barcode Not Found screen cannot describe the food, so it offers a typed lookup
     instead ("Claude Estimate", Describe the food for Claude, Ask Claude for an Estimate); the draft keeps the barcode.
  3. Refresh Nutrients (ai_allow_lookup): POST /api/foods/{id}/refresh-nutrients?claude=1 first fills from the source as before, then, when
     the setting, switch and key allow it, one Claude request (ai.fill_micros, tool record_micros, max 400 tokens, the food's name, brand,
     serving and macros in <food> tags as data) estimates the still blank micronutrients. Only null values are written, never an existing one;
     values out of range or not asked are dropped. They are marked in foods.ai_micros (comma list, added in place, returned as the list
     `ai_micros`; editing a value drops its mark) and named "Claude estimated ... These are estimates." in the picker and the food form.
     The answer adds `claude_filled`, `claude_note` (cap or failure, never an error) and `claude_capped`; `filled` includes both.
     Without a source (no id or barcode) and with Claude allowed the food is still refreshed by Claude, and
     GET /api/foods/missing-nutrients?claude=1 then lists such foods too. Today's and Settings' bulk buttons ask once per batch
     ("Uses up to 10 of your ... requests", status micros=N) and stop asking Claude for the rest of a batch at the cap.
     A source rate limit or outage still answers 429 or 502 as before. Off, the claude flag is ignored.
  4. Import Recipe, Read With Claude (ai_allow_recipe), text and photos (v61, issue #35), sends at once without the confirm notice, and
     the Auto-Match After Import Claude step right after it runs with no confirm and no extra tap. The line under the text button shows
     the cost beforehand ("Up to about 0.11 cents per import ... N of M Claude requests left this month."); at the cap the buttons are
     disabled with the cap note, and a 429 shows that note. The label photo, typed lookup, Match Selected With Claude, Ask Claude on a row
     and the bulk Refresh Nutrients batches keep the Confirm before using Claude behavior.
- Cost estimates (GET /api/ai/status `action_costs`, ai.action_costs, from the same token figures as the cost notice, conservative: text at
  its longest typical size, outputs at the notice's upper estimate). Prices are the user's active prices when set (personal prices on a
  personal key, else the admin prices), otherwise the Haiku 5.5 sample prices 0.10 USD input and 0.50 USD output per million tokens
  (`sample: true`, said under the table). These are estimates, not bills; the real cost is in Settings from ai_usage.

  | Action (estimates) | Tokens in / out | Sample prices |
  |---|---|---|
  | Label photo (1 photo) | 2300 / 400 | about 0.04 cents |
  | Claude lookup (typed, 200 characters) | 700 / 400 | about 0.03 cents |
  | Recipe import from text (8000 characters) | 2900 / 1700 | about 0.11 cents |
  | Claude match, 15 ingredients | 7650 / 2400 | about 0.2 cents |
  | Missing nutrients, one food | 600 / 150 | about 0.01 cents |
  | Heavy month: 30 lookups, 30 nutrient fills, 10 label photos, 8 recipe imports, 8 matches (86 requests) | | about 0.04 USD |

  The issue's older figures (0.3 to 2 cents per action, about 1 USD a month) assumed 1 and 5 USD per million tokens; at those prices the
  same heavy month is about 0.41 USD.

## Count, a Blank Unit and Typed Units (v61 issue #34, v62 issue #36)

- Issue #36 (v62): the Count unit shows lowercase, "count", in every unit selector and everywhere it is displayed (units.LABELS, util.js
  unitChoices, IMPORT_UNITS). The None choice is gone: every unit control (import review row, Match Ingredients amount editor, picker) ends
  with Custom, which reveals a text box ("Your Unit", placeholder "pinch, can, clove") for the user's own unit; empty stays blank. dom.js
  `unitControl` is a select plus that box and reads like a select (.value, change event); the picker wheel has a Custom row and a "Your Unit"
  box under it. Typed units are saved as typed (`units.unit_or_blank`, util.js `unitToSave`): trimmed, spaces tidied, control characters
  dropped, at most 30 characters (units.MAX_UNIT; the server answers 400 past it), known words and aliases still become their canonical
  unit ("Cups" is cup, "Count" is count), anything else keeps its case ("Pinch"). A typed unit is any unit the server does not know
  (`units.is_custom`): it converts like count (the label's count word when the label is one, matching case and plural, else one serving per
  1), `grams` is None for it, and `core.check_amount_unit` accepts it for entries, previews, recipe rows and matches (available_units does
  not list it). It is shown as typed. match_amount and `matchAmount` keep the typed word and give no Check Amount. `available_units` no longer
  lists the blank unit, but "" still saves (a plain count), and an entry or recipe row with a typed or blank unit reopens in the picker on
  Custom with the word. Typed units are not collected into later selectors; the user types them again (the issue's "if simple" option was not
  taken).
- Issue #34 (v61): units.py `count` and the blank unit `""` (also accepted as None, "-" or "none" through `units.unit_or_blank`)
  are offered for every food (after the other units) and by every unit selector built from it (picker, Match
  Ingredients amount editor, recipe log). Both are a plain count: `servings_for` gives the label's own count word when the label is one
  ("3 count" on a "2 slice" label is 1.5 servings), else one label serving per 1. `core.check_amount_unit` accepts them, so entries,
  previews, recipe rows and matches may use them (an entry unit may be ""). A last used blank unit is kept by the quick lists.
- `match_amount` (and util.js `matchAmount`): no amount (None, 0, empty) gives None for any unit. Blank, Count and the other PLAIN_COUNTS
  use the label's count word, else servings, the same as before for piece or each. Nothing is guessed.
- Recipe lines (meal_items src_*): amount and unit are optional everywhere. POST /api/meals/import and the review screen save a line with
  neither as plain text ("salt, to taste"); the review unit box is a unit control (count, weights and volumes, and Custom for any word the recipe
  used or the user types). Claude's import leaves a missing unit null (`recipe_ai.clean_unit`, the tool text says never to guess). The Cooking view and
  logs show them as text (cookIngredient keeps a line without an amount unchanged when scaling; a blank unit shows the bare amount).
- Match Ingredients Edit Amount: an empty amount keeps the line as plain text (skips the row) instead of an error.
- Not changed: the food form serving unit stays free text (count works typed), and the recipe total yield stays weight or volume only.
