# JustWatch → Seerr Sync

Small Docker service that synchronises a JustWatch list into Seerr. It is designed
to run as a separate service in the CineCircle stack and does not modify SchröDrive.

## What it does

On each cycle the service:

1. authenticates to JustWatch through Firebase's HTTP API;
2. refreshes the Firebase token automatically when it expires;
3. reads the configured JustWatch custom list through GraphQL;
4. resolves the JustWatch item to its `externalIds.tmdbId` (the JustWatch
   `objectId` is not a TMDB ID);
5. sends a movie request or a TV request to Seerr;
6. uses `seasons: "all"` for TV, leaving season and future-episode monitoring to
   Seerr/Sonarr;
7. records successfully handled TMDB IDs in SQLite to avoid duplicate requests.

The service uses no external browser, Playwright or FlareSolverr. JustWatch
credentials are used only for the Firebase login and the refresh token is stored
with filesystem mode `600`.

## JustWatch list configuration

Use `JUSTWATCH_LIST_ID` for a custom list. The value is the `tl-...` identifier in
the JustWatch list URL, for example:

```env
JUSTWATCH_LIST_ID=tl-us-6f03013d-945d-4387-8167-b91a3efd37a7
```

If `JUSTWATCH_LIST_ID` is empty, the service falls back to the account's general
JustWatch watchlist. Custom lists and the general watchlist use the same JustWatch
account and credentials.

## Configuration

Required values:

- `JUSTWATCH_FIREBASE_API_KEY` — Firebase web API key used by JustWatch;
- `JUSTWATCH_CREDENTIALS_FILE` — host path to a JSON file containing `email` and
  `password`; never commit this file;
- `SEERR_URL` — normally `http://seerr:5055` inside the CineCircle network;
- `SEERR_API_KEY` — Seerr API key; never commit it.

Optional values:

- `JUSTWATCH_LIST_ID` — custom list ID;
- `JUSTWATCH_COUNTRY` — default `IT`;
- `JUSTWATCH_LANGUAGE` — default `it`;
- `JUSTWATCH_LIST_PAGE_SIZE` — default `1000`;
- `SEERR_DRY_RUN` — default `true`;
- `SEERR_IS_4K` — default `false`;
- `SYNC_INTERVAL_SECONDS` — default `21600` (six hours);
- `STATE_DB` — default `/data/state.sqlite`.

## Dry-run and production flow

Start with `SEERR_DRY_RUN=true`. The service logs the exact TMDB IDs and Seerr
payloads without creating requests. Review the list and payloads, then set
`SEERR_DRY_RUN=false` only after configuring a valid Seerr API key.

Successful requests are persisted in SQLite. HTTP 409 responses are treated as
already-present requests. Failed requests are not marked as completed and can be
retried on the next cycle.

## Docker

The included compose file expects the existing external `cinecircle_default`
network. A local `.env` file can provide the values without entering secrets in
the compose file:

```bash
docker compose up -d --build
docker compose logs -f justwatch-seerr-sync
```

For production, use the versioned image and the CineCircle stack compose file;
do not mount a validation-runtime source tree over the container.

## Relationship to the original project

This project was inspired by
[JustWatch Watchlist Importer & Exporter](https://github.com/DHDS-2811/JustWatch_watch_list_importer_exporter),
but it is maintained separately. The original project is a browser-token-based
CLI for importing/exporting the general watchlist. This service adds Firebase
token refresh, custom-list GraphQL queries, TMDB identity mapping, SQLite state,
Docker deployment and Seerr requests.

The JustWatch GraphQL endpoint is unofficial and may change; keep the request
queries isolated and test with dry-run after upstream changes.
