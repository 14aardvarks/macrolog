# Macrolog

Macrolog is a small self-hosted calorie and macro tracker for a household. It is built to be quick: pick up the phone, find the food, enter the amount, put the phone down. It works without any AI service. Claude is an optional helper that reads nutrition labels from photos.

## Screenshots

| Today | Add | Picker | Settings |
| --- | --- | --- | --- |
| ![Today](docs/screenshots/phone-today.png) | ![Add](docs/screenshots/phone-add.png) | ![Picker](docs/screenshots/phone-picker.png) | ![Settings](docs/screenshots/phone-settings.png) |

Dark mode follows the device setting, and the layout also works on desktop.

![Today, dark mode](docs/screenshots/phone-today-dark.png)
![Today, desktop](docs/screenshots/desktop-today.png)
![Picker, desktop](docs/screenshots/desktop-picker.png)

## Features

- Log food by searching, by scanning a barcode, or from favorites, yesterday's entries and saved recipes, with a Meal selector to show one meal at a time.
- Barcode lookups use Open Food Facts first, then USDA FoodData Central branded foods. Text search uses USDA FoodData Central. While you type, the search box looks only at your own foods and favorites (`remote=0`). Pressing Enter or the Search button also queries USDA (`remote=1`). Every food found is saved in your own database.
- Nutrients are stored per label serving. The amount picker offers the units the label allows, with grams, ounces, cups and tablespoons converted where the label makes that possible. Conversions that rely on an estimate are marked as estimated.
- Custom foods can be created by hand.
- The Today screen shows calorie and macro bars against your targets, with entries grouped by meal.
- Each user has their own daily goal (calories and the carb, protein and fat split) and start screen.
- Barcode scanning uses the browser's BarcodeDetector when it exists. Otherwise a vendored ZXing decoder (Apache-2.0, in `app/static/vendor`) loads on demand, then a photo fallback, then typed digits.
- Light and dark themes follow the system setting.
- Optional: Claude reads a nutrition label from one to three photos. You check the draft before anything is saved.
- Sign in with a local password, with optional single sign-on through OpenID Connect.

## Using the app

The same guide is in Settings under "How to use Macrolog".

- Tap Add, then pick from Favorites, Yesterday or Recipes, or search, scan, or type the barcode digits. Set the amount and tap Log.
- The Meal selector on Add filters the lists by meal. All shows everything.
- In the picker, the wheel chooses the unit, and the chips set 1/4 to 2 servings. Macros update live.
- A food opens with the amount and unit from your last entry. Turn this off in Settings with "Start from my last entry" to open on the label's serving instead.
- Tap the star to make a favorite. On Today, "Save today as a recipe" makes a recipe you can log later.
- If a food is not found, ask Claude to read the label photo (if set up) or enter it manually, and check the numbers.
- Each user has their own log, goals and settings. Foods are shared.

## Quick start

You need Docker with the Compose plugin.

```
cp .env.example .env
# Edit .env and set SECRET_KEY (see the configuration table)
docker compose up -d --build
docker compose exec -it macrolog python -m app.auth_cli add-user alice --name "Alice"
```

Open http://localhost:8000 and sign in as the user you created. The port is published on `127.0.0.1` only. See the reverse proxy section to expose it.

## Configuration

All settings are environment variables read from `.env`. Anything left empty uses the default shown.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | none, required | Signs the session cookie. Must be at least 32 characters or the app refuses to start. Changing it signs everyone out. |
| `DB_PATH` | `/data/macrolog.db` in the image | SQLite database file. The image places it on the `macrolog-data` volume. |
| `LOCAL_LOGIN` | `1` | Set to `0` to turn off password sign-in. Do this only when SSO is configured. |
| `ADMIN_USER`, `ADMIN_PASSWORD` | empty | Creates this user at startup, only while the users table is empty. The password needs at least 8 characters. Remove both after the first start. |
| `OIDC_ISSUER` | empty | authentik issuer URL, for example `https://auth.example.com/application/o/macrolog/`. SSO stays off unless `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `PUBLIC_URL` are all set. |
| `OIDC_CLIENT_ID` | empty | Client ID of the authentik provider. |
| `OIDC_CLIENT_SECRET` | empty | Client secret for a confidential client. Sent only when set. |
| `OIDC_NAME` | `authentik` | Label on the sign-in button. |
| `OIDC_ALLOW_SIGNUP` | `0` | `0` refuses SSO logins that do not match an existing account. `1` lets any successful SSO login create an account. |
| `PUBLIC_URL` | empty | Public address of the app, for example `https://macrolog.example.com`. Used for the SSO redirect URI and as the expected origin for state-changing requests. |
| `TRUST_PROXY` | `0` | Set to `1` behind your own reverse proxy. The login rate limit then reads the client address from the last `X-Forwarded-For` entry. |
| `COOKIE_SECURE` | `0` | Set to `1` when the site is served over HTTPS, so the session cookie is marked Secure. |
| `ANTHROPIC_API_KEY` | empty | Turns on the Claude label reader. The "Ask Claude" option appears only when this is set. |
| `AI_MODEL` | `claude-haiku-5-5` | Model used for label reading. Haiku is recommended. Only Haiku models are forced to use the label tool. Other models are allowed to choose, and a reply without the tool result is shown as an error. |
| `AI_MONTHLY_REQUEST_CAP` | `100` | Label-reading requests allowed per calendar month, counted for the whole household. |
| `AI_PRICE_IN_PER_MTOK` | empty | Input price of the model in USD per million tokens. Used only to show costs. Set both price variables, or the app shows "Cost not available". Look up the current price on Anthropic's pricing page. |
| `AI_PRICE_OUT_PER_MTOK` | empty | Output price of the model in USD per million tokens. |
| `FDC_API_KEY` | `DEMO_KEY` | USDA FoodData Central key. Use a real free key from https://api.data.gov/signup/ because `DEMO_KEY` is heavily rate limited. |

Generate a `SECRET_KEY` with:

```
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Adding users

Local users are created from the command line inside the container. The password is read with a no-echo prompt, so use `-it` for the commands that ask for one.

```
docker compose exec -it macrolog python -m app.auth_cli add-user alice --name "Alice" --email alice@example.com
docker compose exec -it macrolog python -m app.auth_cli set-password alice
docker compose exec macrolog python -m app.auth_cli set-email alice alice@example.com
docker compose exec macrolog python -m app.auth_cli list-users
```

Usernames are lowercased and may contain letters, digits, `.`, `_`, `-` and `@`, up to 64 characters. Passwords must be 8 to 1024 characters. Five failed sign-ins for one username, or twenty from one address, within 15 minutes trigger a temporary block. Attempts are refused until enough of those failures are more than 15 minutes old.

## Single sign-on with authentik

1. Create an OAuth2/OpenID provider with client type Confidential. Copy the client ID and client secret into `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`.
2. Set the redirect URI to strict mode with the value `PUBLIC_URL/auth/oidc/callback`, for example `https://macrolog.example.com/auth/oidc/callback`.
3. Choose an RS256 signing key certificate. Leave the encryption key empty, because Macrolog reads only signed ID tokens.
4. Set the scopes to `openid`, `email` and `profile`.
5. Turn on "Include claims in id_token".
6. Create an application for the provider. Its slug sets the issuer, `https://auth.example.com/application/o/<slug>/`. Put that exact value in `OIDC_ISSUER`, with the trailing slash. Macrolog adds the slash if it is missing, and the issuer in the discovery document must then match.

Macrolog accepts ID tokens signed with RS256, RS384, RS512, PS256 to PS512, ES256 to ES512 and EdDSA. It checks the issuer, audience, expiry, subject and nonce, and it uses PKCE with state.

**How accounts are matched.** On each SSO sign-in Macrolog tries these steps in order:

1. Find the account already linked to this authentik subject.
2. If the ID token has an email and `email_verified` is exactly `true`, find the local accounts with that email that are not yet linked to SSO. Link the login only when exactly one account matches. The link is made once and is not undone.
3. Otherwise create a new account, using `preferred_username`, or the part of the email before the `@`. If that name is taken, a number is added. This happens only when `OIDC_ALLOW_SIGNUP` is `1`. When it is `0`, which is the default, the login is refused.

**Signup is off by default.** With `OIDC_ALLOW_SIGNUP=0`, nobody can create an account by signing in through SSO. Create each account first with the CLI, and give it the same email address that authentik has for the person:

```
docker compose exec -it macrolog python -m app.auth_cli add-user alice --name "Alice" --email alice@example.com
```

The first time that person signs in with SSO, Macrolog links the login to this account. This linking works only when the ID token has `email_verified` set to `true`. For an existing account, `set-email` stores the address, and the match still depends on `email_verified` at sign-in. Set `OIDC_ALLOW_SIGNUP=1` instead if you want anyone who can sign in to authentik to get an account automatically.

**Making authentik send `email_verified`.** Authentik's stock email mapping may leave the claim out. To be sure it is sent:

1. In the authentik admin interface open Customization, then Property Mappings, and choose Create.
2. Pick Scope Mapping. Name it `Macrolog email`, set the scope name to `email`, and use this expression:

   ```python
   return {"email": request.user.email, "email_verified": True}
   ```

3. Open the Macrolog provider, expand Advanced protocol settings, and add the new mapping to Scopes. Remove the default email mapping so that only one mapping answers the `email` scope.
4. Sign in again with SSO. The claim is read from the new ID token.

This tells Macrolog that every authentik email is verified, so only do it when you control who can have an authentik account and what email they enter. Anyone who can set their authentik email to another person's address could otherwise take over that person's Macrolog account.

If the claim is missing, a user who already has a local account is refused (signup off) or gets a second account (signup on). Accounts created by mistake can only be removed directly from the `users` table, because the CLI has no delete command.

## Reverse proxy and HTTPS

Run a reverse proxy that terminates TLS, such as Caddy, nginx or Traefik, and forward it to port 8000. Then set:

```
PUBLIC_URL=https://macrolog.example.com
COOKIE_SECURE=1
TRUST_PROXY=1
```

Set `TRUST_PROXY=1` only when the proxy is the only route to port 8000. Otherwise clients can send their own `X-Forwarded-For` header and get around the per-address login limit. Phone browsers allow the camera only on HTTPS pages. Without HTTPS the app falls back to choosing a photo of the barcode, or to typing the digits.

The Compose file publishes port 8000 on `127.0.0.1` only, so a reverse proxy on the same host can reach it and nothing else can. To expose it to other machines, for example a proxy on another host or plain HTTP on your LAN, change the `ports` entry in `docker-compose.yml` to `"8000:8000"` and protect it with a firewall.

## Claude label reader (optional)

When `ANTHROPIC_API_KEY` is set, the Not found screen offers "Ask Claude" as an option. The browser re-encodes each photo as a JPEG with at most 1280 px on the long side, and sends one to three photos with an optional barcode and a short hint. The server sends them to the Messages API with a forced tool call, which returns the label values as printed, per serving. The result is shown as an editable draft with warnings, for example when calories do not match the macros by more than 20 percent, when a serving is missing, or when a value looks implausible. Nothing is saved until you confirm. The API key is never sent to the browser and is never logged.

The cap is a request count, not a money limit. `AI_MONTHLY_REQUEST_CAP` applies to the whole household for each calendar month. A request is counted before it is sent and released if the call fails. Requests are not retried. Each request's token counts are kept in the `ai_usage` table. The Settings screen shows how many requests are used.

Before each Claude request the app shows a notice with what will be sent, how many of the monthly requests it uses, and the estimated cost. Nothing is sent until you tap Continue. Each person can turn the notice off in Settings with "Confirm before using Claude". The estimate assumes about 1,600 input tokens per photo, 700 for the instructions and 400 output tokens. The monthly cost in Settings is computed from the real token counts stored in `ai_usage`.

Settings also has "Show servings as", which switches serving amounts between fractions (1/2) and decimals (0.5). Typing accepts both.

## Backups

All data is one SQLite file, `macrolog.db`, in the `macrolog-data` volume. While the app runs there are also `-wal` and `-shm` files next to it. Copying the raw files while the app runs can miss recent changes. Use SQLite's backup function, which is safe while the app runs:

```
docker compose exec macrolog python -c "import sqlite3; src = sqlite3.connect('/data/macrolog.db'); dst = sqlite3.connect('/tmp/backup.db'); src.backup(dst); dst.close(); src.close()"
docker compose cp macrolog:/tmp/backup.db ./macrolog-backup.db
```

You can also stop the app with `docker compose stop`, copy the volume contents, and start it again.

Keep the database on local disk. Do not put the volume or `DB_PATH` on NFS or another network filesystem, because SQLite in WAL mode can corrupt its files there.

## Development

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
node --test tests/ui
```

Run pytest as `python -m pytest`, so the `app` package is on the import path. The Python tests run offline and stub the network. The browser helper tests use Node's built-in test runner and need no npm packages.

Layout: `app/` holds the FastAPI backend (`auth.py`, `core.py`, `ai.py`, `lookup.py`, `units.py`, `db.py`). `app/static/` holds the frontend, which is plain HTML, CSS and ES modules with no build step.

## Known gaps

- The author has not tested live Open Food Facts and USDA lookups, or the camera on a real device.
- Not built yet: an iOS app, trends, and recipes built from ingredients.

## License

MIT. See [LICENSE](LICENSE).
