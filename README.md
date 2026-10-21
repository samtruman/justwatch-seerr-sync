# JustWatch → Seerr Sync

Separate Docker service for synchronising an authenticated JustWatch list into Seerr.

Set `JUSTWATCH_LIST_ID` to a custom-list ID to use that list (for example the dedicated
`Seerr` list). IDs have the `tl-...` form and are copied from the JustWatch list URL.
When it is empty, the service falls back to the account's general watchlist.

The default is `SEERR_DRY_RUN=true`; it reads and logs the planned Seerr requests without creating them. The service refreshes the JustWatch Firebase token automatically and stores only sync state in SQLite.

Required environment values:

- `JUSTWATCH_FIREBASE_API_KEY`
- `JUSTWATCH_CREDENTIALS_FILE` (JSON file containing `email` and `password`, never committed)
- `JUSTWATCH_LIST_ID` (optional custom-list ID; the production stack sets this explicitly)
- `SEERR_API_KEY`
- `SEERR_URL`

The JustWatch GraphQL endpoint is unofficial and may change. The first test must remain dry-run; enable requests only after reviewing the logged titles and Seerr payloads.

This project was inspired by [JustWatch Watchlist Importer & Exporter](https://github.com/DHDS-2811/JustWatch_watch_list_importer_exporter), but the runtime service is maintained separately because it uses direct Firebase token refresh, custom-list GraphQL queries, SQLite state and Seerr requests.
