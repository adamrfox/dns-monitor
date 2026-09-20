import ipaddress

import requests
import urllib3


class UnifiError(RuntimeError):
    pass


class UnifiClient:
    """
    Client for a UniFi OS console's local Network Integration API (v1), using an
    API key (Settings > Control Plane > Integrations > Create API Key). This is
    the only supported auth path here - username/password hits 2FA on accounts
    that have it enabled, which the API has no way to satisfy.
    """

    def __init__(self, controller_url: str, site: str, auth: dict, verify_ssl=False, **_ignored):
        self.base_url = controller_url.rstrip("/") + "/proxy/network/integration/v1"
        self.site_name = site
        self.verify_ssl = verify_ssl
        self._site_id = None

        if auth.get("method") != "api_key":
            raise NotImplementedError(
                "Only auth.method 'api_key' is supported - password auth is blocked by 2FA "
                "on UniFi OS consoles and isn't implemented."
            )

        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers["X-API-KEY"] = auth["api_key"]
        self.session.headers["Accept"] = "application/json"

        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get(self, path: str) -> dict:
        resp = self.session.get(f"{self.base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def _resolve_site_id(self) -> str:
        if self._site_id is not None:
            return self._site_id

        payload = self._get("/sites")
        for site in payload.get("data", []):
            if site.get("internalReference") == self.site_name:
                self._site_id = site["id"]
                return self._site_id

        raise UnifiError(f"No site found with internalReference={self.site_name!r} in {payload}")

    def get_wan_ip(self) -> str:
        site_id = self._resolve_site_id()
        payload = self._get(f"/sites/{site_id}/devices")

        public_ip_devices = []
        for device in payload.get("data", []):
            ip = device.get("ipAddress")
            if ip and not ipaddress.ip_address(ip).is_private:
                public_ip_devices.append(device)

        if not public_ip_devices:
            raise UnifiError(f"No device with a public IP found (gateway offline?): {payload}")
        if len(public_ip_devices) > 1:
            names = [d.get("name") for d in public_ip_devices]
            raise UnifiError(f"Multiple devices with public IPs found, ambiguous gateway: {names}")

        return public_ip_devices[0]["ipAddress"]
