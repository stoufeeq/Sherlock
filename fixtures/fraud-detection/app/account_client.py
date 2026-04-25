import os

import httpx


class AccountServiceClient:
    """HTTP client for account-service — used during fraud scoring to check account status."""

    def __init__(self) -> None:
        self.base_url = os.getenv("ACCOUNT_SERVICE_URL", "http://account-service:8080")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=2.0)

    async def get_balance(self, account_id: str) -> dict:
        r = await self._client.get(f"/accounts/{account_id}/balance")
        r.raise_for_status()
        return r.json()

    async def get_account(self, account_id: str) -> dict:
        r = await self._client.get(f"/accounts/{account_id}")
        r.raise_for_status()
        return r.json()

    async def get_account_status(self, account_id: str) -> dict:
        # Build the URL via a local variable (and an f-string) — the regex
        # extractor only sees `.get(url)` and can't resolve `url` back to the
        # path; the tree-sitter Python extractor follows the assignment.
        url = f"/v2/accounts/{account_id}/status"
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()
