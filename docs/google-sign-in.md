# Google sign-in (Supabase Auth)

Sign-in is **off** until two settings are filled in. With it off, Lattice works exactly as before
(anonymous per-browser identity). With it on, every `/api` route needs a signed-in Google account.

Code: `web/auth.py` (flow, token checks, the gate) · tests: `tests/test_auth.py`.

## 1. Google Cloud: an OAuth client

1. <https://console.cloud.google.com> → **APIs & Services → OAuth consent screen**: set it up
   (External, app name, support email). Scopes: the defaults (`email`, `profile`, `openid`).
2. **Credentials → Create credentials → OAuth client ID → Web application**.
3. **Authorized redirect URIs**: add your Supabase callback, exactly:
   `https://<project-ref>.supabase.co/auth/v1/callback`
4. Copy the **Client ID** and **Client secret**.

## 2. Supabase: turn on Google

1. **Authentication → Sign In / Providers → Google**: enable it, then paste the Client ID and secret.
2. **Authentication → URL Configuration → Redirect URLs**: add every address Lattice runs at:
   - `http://127.0.0.1:8080/auth/callback` (local)
   - `https://<your-domain>/auth/callback` (production)

   Supabase refuses to redirect anywhere not on this list. A missing entry shows up as the
   sign-in landing on your Supabase **Site URL** instead of coming back to Lattice.
3. **Project Settings → API**: copy the **Project URL** and the **anon / publishable** key.

## 3. Lattice: `.env`

```env
LATTICE_SUPABASE_URL=https://<project-ref>.supabase.co
LATTICE_SUPABASE_ANON_KEY=<anon key>
LATTICE_PUBLIC_URL=https://<your-domain>     # production only; empty works locally
# optional
LATTICE_SUPABASE_JWT_SECRET=                 # legacy HS256 projects: check tokens offline
LATTICE_AUTH_REQUIRED=true                   # false = guests may use the app without signing in
```

Restart the server (`python -m scripts.serve`). The page now opens on **Continue with Google**.

## How it works

- `GET /auth/login` sends the browser to Supabase with a PKCE challenge. The verifier waits in a
  10-minute httponly cookie scoped to `/auth`.
- `GET /auth/callback` exchanges the code for a session and stores the access and refresh tokens
  in httponly, `SameSite=Lax` cookies (`Secure` on https). No token is ever readable by JavaScript.
- On every request, `AuthMiddleware` checks the access token locally against the project's JWKS
  (asymmetric keys), or the JWT secret if one is set. With neither, it asks Supabase once per
  token. An expired token is refreshed, and the rotated cookies are written onto whatever
  response goes out, including video files and the SSE progress stream.
- If Supabase is unreachable, that request is refused, but the session is kept. A revoked
  session clears the cookies.
- The gate denies by default: only `/`, `/health`, `/static/*`, `/auth/*`, `/api/auth/*` and the
  admin console (which keeps its own `LATTICE_ADMIN_TOKEN` gate) are open without a session.
- `request.state.auth.user` is the signed-in `AuthUser`. `web/users.py` uses the Supabase user
  id as the identity, so usage and spend in the admin console are tracked per account (with email
  and name).

## Each account sees only its own work

With sign-in on, videos, slide decks, lesson threads and their render jobs belong to whoever made
them (`web/ownership.py`, index at `out/web/owners.json`). Lists show only your own. Someone else's
id answers 404, exactly like a missing one. With sign-in off, everything stays shared as before.

Work made before sign-in existed has no owner, so nobody sees it. Hand it to one account (it must
have signed in once):

```
python -m scripts.claim_unowned --email you@gmail.com --dry-run   # preview
python -m scripts.claim_unowned --email you@gmail.com
```

It is safe while the server runs: the server sees the change at once, and neither side overwrites
the other.

## Adding another provider

Enable it in Supabase, then add its name to `PROVIDERS` in `web/auth.py`. Link to
`/auth/login?provider=<name>` from the sign-in screen.
