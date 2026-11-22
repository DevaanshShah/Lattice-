# Lattice site (static)

Homepage, privacy policy and terms. No build step. Hosted separately from the app (Vercel free, or
GitHub Pages), so these links stay up if the app server is down or moves. The app also serves its own
copies of the two legal pages from `web/static/`; keep the wording in sync.

Two placeholders are filled in before publishing: `{{APP_URL}}` (the app's https address) and
`{{CONTACT}}` (the public contact email).

    powershell -File siteill.ps1 -AppUrl https://lattice-app.duckdns.org -Contact you@example.com

That writes the finished pages to `site-out\`, which is the folder to deploy.
