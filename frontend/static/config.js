// Where the backend lives. Empty = the same address that served this page (the default: one server
// serves both the UI and the API, nothing to configure). On a split deploy (UI on Vercel, API on
// your own server) set it to the API's origin, e.g. "https://api.example.com", before publishing.
// The two must share a registrable domain (app.example.com + api.example.com), or the browser
// will not send the sign-in cookies. See docs/DEPLOY.md, "Split deploy".
window.LATTICE_API = "";
// Every request that leaves the page for the backend goes through U(): one place decides the address.
window.U = (path) => String(window.LATTICE_API || "").replace(/\/$/, "") + path;
