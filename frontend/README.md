# Lattice frontend

Plain static files, no build step: `index.html` plus `static/*.js|css`. It talks to the backend
(the Python app at the repo root) over HTTP, and can be served either by that backend (the default) or
hosted on its own, for example on Vercel.

## Which address does it call?

`static/config.js` holds `window.LATTICE_API`. Every request goes through `U()` in that file.

- `""` (the default): the same address that served the page. One server, nothing to configure.
- `"https://api.example.com"`: a separate backend. See "Split deploy" in `docs/DEPLOY.md`.

A test (`tests/test_split_deploy.py`) fails if a script sends a backend URL without going through `U()`.

## Publish it separately (Vercel)

```powershell
powershell -File frontend\build.ps1 -Api https://api.example.com -Contact you@example.com
```

That writes `frontend-out\`: this folder with the API address and contact email filled in. Upload that
folder to Vercel (no framework, no build command). The API and the frontend must share a registrable
domain, e.g. `app.example.com` and `api.example.com`, or the browser will not send the sign-in cookies.

The owner's admin console is not here: it is part of the backend (`web/static/admin.*`).
