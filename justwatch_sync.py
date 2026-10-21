import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests

LOG = logging.getLogger("justwatch-sync")
JW_GRAPHQL = "https://apis.justwatch.com/graphql"
FIREBASE_LOGIN = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
FIREBASE_REFRESH = "https://securetoken.googleapis.com/v1/token"

WATCHLIST_QUERY = """query GetTitleListV2($sortBy: TitleListSortingV2!, $first: Int!, $filter: TitleFilter, $language: Language!, $country: Country!, $titleListType: TitleListTypeV2!, $after: String) {
  titleListV2(sortBy: $sortBy, first: $first, filter: $filter, language: $language, country: $country, titleListType: $titleListType, after: $after) {
    pageInfo { endCursor hasNextPage }
    edges { node { id objectId objectType content(country: $country, language: $language) { title originalReleaseYear externalIds { imdbId tmdbId } } } }
  }
}"""

CUSTOM_LIST_QUERY = """query GetCustomList($id: ID!, $first: Int!, $language: Language!, $country: Country!) {
  node(id: $id) {
    __typename
    ... on GenericTitleList {
      id
      content(country: $country, language: $language) { name }
      titles(country: $country, first: $first) {
        totalCount
        edges {
          node {
            __typename
            ... on Movie {
              objectId objectType
              content(country: $country, language: $language) { title originalReleaseYear externalIds { imdbId tmdbId } }
            }
            ... on Show {
              objectId objectType
              content(country: $country, language: $language) { title originalReleaseYear externalIds { imdbId tmdbId } }
            }
          }
        }
      }
    }
  }
}"""


def env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


class JustWatch:
    def __init__(self, credentials: Path, token_state: Path):
        data = json.loads(credentials.read_text())
        self.email = data["email"]
        self.password = data["password"]
        self.api_key = os.environ["JUSTWATCH_FIREBASE_API_KEY"]
        self.id_token = ""
        self.refresh_token = ""
        self.token_state = token_state
        if token_state.exists():
            try:
                self.refresh_token = json.loads(token_state.read_text()).get("refreshToken", "")
            except (OSError, ValueError):
                LOG.warning("Ignoring unreadable JustWatch token state")
        self.session = requests.Session()
        self.session.headers.update({
            "Origin": "https://www.justwatch.com", "Referer": "https://www.justwatch.com/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
            "Accept": "*/*", "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        })

    def login(self) -> None:
        response = self.session.post(f"{FIREBASE_LOGIN}?key={self.api_key}", json={
            "email": self.email, "password": self.password, "returnSecureToken": True,
        }, timeout=30)
        response.raise_for_status()
        data = response.json()
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self._save_token_state()
        LOG.info("JustWatch login succeeded; token lifetime=%ss", data.get("expiresIn", "unknown"))

    def refresh(self) -> None:
        response = self.session.post(f"{FIREBASE_REFRESH}?key={self.api_key}", json={
            "grant_type": "refresh_token", "refresh_token": self.refresh_token,
        }, timeout=30)
        response.raise_for_status()
        data = response.json()
        self.id_token = data["id_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self._save_token_state()
        LOG.info("JustWatch token refreshed")

    def _save_token_state(self) -> None:
        self.token_state.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_state.with_suffix(".tmp")
        temporary.write_text(json.dumps({"refreshToken": self.refresh_token}))
        os.chmod(temporary, 0o600)
        temporary.replace(self.token_state)
        os.chmod(self.token_state, 0o600)

    def watchlist(self) -> list[dict[str, Any]]:
        if not self.refresh_token:
            self.login()
        results: list[dict[str, Any]] = []
        cursor = ""
        while True:
            variables = {
                "sortBy": "LAST_ADDED", "first": int(os.getenv("JUSTWATCH_PAGE_SIZE", "50")),
                "filter": {"includeTitlesWithoutUrl": True}, "language": os.getenv("JUSTWATCH_LANGUAGE", "it"),
                "country": os.getenv("JUSTWATCH_COUNTRY", "IT"), "titleListType": "WATCHLIST", "after": cursor,
            }
            response = self.session.post(JW_GRAPHQL, headers={"Authorization": f"Bearer {self.id_token}"}, json={
                "operationName": "GetTitleListV2", "variables": variables, "query": WATCHLIST_QUERY,
            }, timeout=30)
            if response.status_code == 401:
                self.refresh()
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(payload["errors"])
            page = payload["data"]["titleListV2"]
            for edge in page.get("edges", []):
                node = edge.get("node", {})
                content = node.get("content") or {}
                external_ids = content.get("externalIds") or {}
                results.append({
                    "id": external_ids.get("tmdbId") or node.get("objectId"), "type": "movie" if node.get("objectType") == "MOVIE" else "show",
                    "title": content.get("title"), "year": content.get("originalReleaseYear"),
                    "imdbId": (content.get("externalIds") or {}).get("imdbId"),
                })
            if not page.get("pageInfo", {}).get("hasNextPage"):
                return results
            cursor = page["pageInfo"]["endCursor"]

    def custom_list(self, list_id: str) -> list[dict[str, Any]]:
        if not self.refresh_token:
            self.login()
        while True:
            response = self.session.post(JW_GRAPHQL, headers={"Authorization": f"Bearer {self.id_token}"}, json={
                "operationName": "GetCustomList",
                "variables": {
                    "id": list_id,
                    "first": int(os.getenv("JUSTWATCH_LIST_PAGE_SIZE", "1000")),
                    "language": os.getenv("JUSTWATCH_LANGUAGE", "it"),
                    "country": os.getenv("JUSTWATCH_COUNTRY", "IT"),
                },
                "query": CUSTOM_LIST_QUERY,
            }, timeout=30)
            if response.status_code == 401:
                self.refresh()
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(payload["errors"])
            node = payload.get("data", {}).get("node") or {}
            if node.get("__typename") != "GenericTitleList":
                raise RuntimeError(f"JustWatch list not found or not a custom list: {list_id}")
            titles = node.get("titles") or {}
            results: list[dict[str, Any]] = []
            for edge in titles.get("edges", []):
                item = edge.get("node") or {}
                content = item.get("content") or {}
                results.append({
                    "id": (content.get("externalIds") or {}).get("tmdbId") or item.get("objectId"),
                    "type": "movie" if item.get("objectType") == "MOVIE" else "show",
                    "title": content.get("title"),
                    "year": content.get("originalReleaseYear"),
                    "imdbId": (content.get("externalIds") or {}).get("imdbId"),
                })
            LOG.info("JustWatch custom list %s (%s) read: %d/%d items", list_id, (node.get("content") or {}).get("name"), len(results), titles.get("totalCount", len(results)))
            return results


class Sync:
    def __init__(self, db_path: Path):
        self.db = sqlite3.connect(db_path)
        self.db.execute("create table if not exists seen (tmdb_id integer primary key, media_type text not null, title text, last_seen text default current_timestamp)")
        self.db.commit()
        self.seerr_url = os.environ["SEERR_URL"].rstrip("/")
        self.seerr_key = os.environ["SEERR_API_KEY"]
        self.dry_run = env_bool("SEERR_DRY_RUN", True)
        self.is4k = env_bool("SEERR_IS_4K", False)

    def request(self, item: dict[str, Any]) -> None:
        tmdb_id = int(item["id"])
        exists = self.db.execute("select 1 from seen where tmdb_id=?", (tmdb_id,)).fetchone()
        if exists:
            return
        body = {"mediaType": "tv" if item["type"] == "show" else "movie", "mediaId": tmdb_id, "is4k": self.is4k}
        if item["type"] == "show":
            body["seasons"] = "all"
        LOG.info("%s %s (%s) -> Seerr %s", "DRY-RUN" if self.dry_run else "REQUEST", item["title"], tmdb_id, body)
        if not self.dry_run:
            response = requests.post(f"{self.seerr_url}/api/v1/request", headers={"X-Api-Key": self.seerr_key}, json=body, timeout=30)
            if response.status_code == 409:
                LOG.info("Already present in Seerr: %s (%s)", item["title"], tmdb_id)
            else:
                if not response.ok:
                    LOG.error("Seerr rejected %s (%s): HTTP %s %s", item["title"], tmdb_id, response.status_code, response.text[:500])
                response.raise_for_status()
        if not self.dry_run:
            self.db.execute("insert or replace into seen (tmdb_id, media_type, title) values (?, ?, ?)", (tmdb_id, item["type"], item["title"]))
            self.db.commit()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    credentials = Path(os.getenv("JUSTWATCH_CREDENTIALS", "/run/secrets/credentials.json"))
    state = Path(os.getenv("STATE_DB", "/data/state.sqlite"))
    state.parent.mkdir(parents=True, exist_ok=True)
    interval = int(os.getenv("SYNC_INTERVAL_SECONDS", "21600"))
    while True:
        try:
            justwatch = JustWatch(credentials, state.with_suffix(".justwatch-token.json"))
            list_id = os.getenv("JUSTWATCH_LIST_ID", "").strip()
            items = justwatch.custom_list(list_id) if list_id else justwatch.watchlist()
            if not list_id:
                LOG.info("JustWatch watchlist read: %d items", len(items))
            sync = Sync(state)
            for item in items:
                sync.request(item)
        except Exception:
            LOG.exception("sync cycle failed")
        if env_bool("RUN_ONCE", False):
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
