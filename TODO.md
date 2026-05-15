# TODO

- [ ] Replace client-side head refresh spam with a server-side “fastest” head URL strategy and refresh cached head URLs every 15 minutes.
- [ ] Implement head cache + periodic refresh task (15 min) in `index.py`.
- [ ] Update `/` and `/heads` routes to use cached head URLs instead of generating a new `?t=` every render.
- [ ] Ensure caching uses minotar.net and avoids per-request timestamp changes (faster + less bandwidth).
- [ ] Run a quick sanity check (python import/lint) and ensure Flask app still starts.

