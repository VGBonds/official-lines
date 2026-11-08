"""Polite HTTP: an honest User-Agent, robots.txt respected, a pause between hits per host."""

import threading
import time
from urllib import robotparser
from urllib.parse import urlsplit

import httpx

PER_HOST_DELAY_SECONDS = 1.5


class Blocked(Exception):
    """robots.txt disallows the URL."""


class PoliteClient:
    def __init__(self, user_agent: str, timeout: float = 20.0):
        self.user_agent = user_agent
        self.client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "en"},
            timeout=timeout,
            follow_redirects=True,
        )
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    def get(self, url: str) -> httpx.Response:
        if not self.allowed(url):
            raise Blocked(f"robots.txt disallows {url}")
        self._wait_for_host(urlsplit(url).netloc)
        response = self.client.get(url)
        response.raise_for_status()
        return response

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            self._robots[base] = self._load_robots(base)
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def _load_robots(self, base: str) -> robotparser.RobotFileParser | None:
        try:
            r = self.client.get(f"{base}/robots.txt")
        except httpx.HTTPError:
            return None
        if r.status_code != 200 or "html" in r.headers.get("content-type", ""):
            return None  # no usable robots.txt: allowed by convention
        rp = robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp

    def _wait_for_host(self, host: str) -> None:
        with self._lock:
            wait = self._last_hit.get(host, 0) + PER_HOST_DELAY_SECONDS - time.monotonic()
            self._last_hit[host] = time.monotonic() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)
