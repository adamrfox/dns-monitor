import logging
from urllib.parse import urlsplit, urlunsplit

import requests

log = logging.getLogger("dns-monitor")


def push_heartbeat(push_url: str, status: str, msg: str) -> None:
    base_url = urlunsplit(urlsplit(push_url)._replace(query=""))
    try:
        requests.get(base_url, params={"status": status, "msg": msg}, timeout=10)
    except Exception:
        log.warning("Failed to push heartbeat to Uptime Kuma", exc_info=True)
