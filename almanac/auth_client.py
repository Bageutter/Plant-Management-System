"""Small client for asking the shared Auth service who is logged in."""

import json
from urllib import error, request


class AuthClient:
    def __init__(self, base_url: str, timeout: int = 3):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("AUTH_URL must be an http(s) URL")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def current_user(self, cookie_header: str) -> dict | None:
        if not cookie_header:
            return None

        auth_request = request.Request(  # noqa: S310 -- base_url is http(s), checked in __init__
            f"{self.base_url}/me",
            headers={"Cookie": cookie_header, "Accept": "application/json"},
        )
        try:
            with request.urlopen(auth_request, timeout=self.timeout) as response:  # noqa: S310 -- http(s) only
                if response.status != 200:
                    return None
                user = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, json.JSONDecodeError):
            return None

        if not isinstance(user, dict) or not isinstance(user.get("id"), int):
            return None
        return user
