"""
Minimal Backblaze B2 client over the native REST API.

Why this exists rather than reusing the harness's puller: `scripts/01_pull_data.py`
imports `fetch_b2_data` from `llaminet/pipeline/scripts/`, and no `pipeline/` repo
exists on this machine, so that path is dead. `simulation_14/analysis/baseline_race/
fetch_swaps_from_b2.py` works but needs `b2sdk`, which is not in the research flake.
`requests` is, so this speaks the B2 v3 API directly.

Credentials are read from model/.env (read-only), same source the baseline_race
helper uses.
"""

from __future__ import annotations

import base64
import io
import time
import os
from pathlib import Path

import requests

DEFAULT_ENV_PATH = "/home/poon/developments/llaminet/model/.env"
AUTH_URL = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"


def read_env(path: str = DEFAULT_ENV_PATH) -> dict:
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"').strip("'")
    return env


class B2:
    def __init__(self, env: dict | None = None, env_path: str = DEFAULT_ENV_PATH):
        self.env = env if env is not None else read_env(env_path)
        self.pool_prefix = self.env.get("B2_POOL_PREFIX", "eth_usdc_0p05")
        self.bucket_name = self.env["B2_BUCKET_NAME"]
        self._auth()

    def _auth(self) -> None:
        key_id = self.env["B2_ACCOUNT_ID"]
        app_key = self.env["B2_ACCOUNT_KEY"]
        token = base64.b64encode(f"{key_id}:{app_key}".encode()).decode()
        r = requests.get(AUTH_URL, headers={"Authorization": f"Basic {token}"}, timeout=60)
        r.raise_for_status()
        j = r.json()
        api = j["apiInfo"]["storageApi"]
        self.api_url = api["apiUrl"]
        self.download_url = api["downloadUrl"]
        self.token = j["authorizationToken"]
        # A restricted application key is already scoped to one bucket.
        self.bucket_id = api.get("bucketId")
        if not self.bucket_id:
            self.bucket_id = self._lookup_bucket_id(j["accountId"])

    def _lookup_bucket_id(self, account_id: str) -> str:
        r = requests.post(
            f"{self.api_url}/b2api/v3/b2_list_buckets",
            headers={"Authorization": self.token},
            json={"accountId": account_id, "bucketName": self.bucket_name},
            timeout=60,
        )
        r.raise_for_status()
        buckets = r.json()["buckets"]
        if not buckets:
            raise RuntimeError(f"bucket {self.bucket_name!r} not visible to this key")
        return buckets[0]["bucketId"]

    def _post(self, endpoint: str, body: dict, tries: int = 5):
        """B2 closes the connection on some large list responses; retry those."""
        last = None
        for attempt in range(tries):
            try:
                r = requests.post(
                    f"{self.api_url}/b2api/v3/{endpoint}",
                    headers={"Authorization": self.token},
                    json=body,
                    timeout=180,
                )
                if r.status_code == 401:
                    self._auth()
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{endpoint} failed after {tries} tries: {last}")

    def list_files(self, prefix: str, page_size: int = 500, max_pages: int = 400) -> list[dict]:
        """Return [{name, size}] for every file under `prefix`."""
        out: list[dict] = []
        start = None
        for _ in range(max_pages):
            body = {"bucketId": self.bucket_id, "prefix": prefix, "maxFileCount": page_size}
            if start:
                body["startFileName"] = start
            j = self._post("b2_list_file_names", body)
            for f in j["files"]:
                out.append({"name": f["fileName"], "size": f["contentLength"]})
            start = j.get("nextFileName")
            if not start:
                break
        return out

    def download(self, file_name: str, tries: int = 4) -> bytes:
        url = f"{self.download_url}/file/{self.bucket_name}/{file_name}"
        last = None
        for attempt in range(tries):
            try:
                r = requests.get(url, headers={"Authorization": self.token}, timeout=600)
                if r.status_code == 401:
                    self._auth()
                    continue
                r.raise_for_status()
                return r.content
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"download {file_name} failed after {tries} tries: {last}")

    def download_to(self, file_name: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.write_bytes(self.download(file_name))
        return dest
