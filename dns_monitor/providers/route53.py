import boto3

from dns_monitor.records import fqdn


def _normalize_name(name: str) -> str:
    # Route53 returns wildcard labels octal-escaped, e.g. "\052.example.com."
    return name.rstrip(".").replace("\\052", "*")


class Route53Error(RuntimeError):
    pass


class Route53Provider:
    def __init__(self, region: str = None, **_ignored):
        self.client = boto3.client("route53", region_name=region)

    def find_hosted_zone_id(self, domain: str) -> str:
        """Resolve a domain to its hosted zone ID. Raises if there's zero or more than one match."""
        dns_name = domain.rstrip(".") + "."
        resp = self.client.list_hosted_zones_by_name(DNSName=dns_name)
        matches = [z for z in resp.get("HostedZones", []) if z["Name"] == dns_name]

        if not matches:
            raise Route53Error(
                f"No hosted zone found for {domain!r} - create one first, or pass --hosted-zone-id explicitly"
            )
        if len(matches) > 1:
            ids = [z["Id"].removeprefix("/hostedzone/") for z in matches]
            raise Route53Error(f"Multiple hosted zones found for {domain!r}: {ids} - pass --hosted-zone-id explicitly")

        return matches[0]["Id"].removeprefix("/hostedzone/")

    def update_record(self, record: dict, ip: str) -> None:
        name = fqdn(record)
        self.client.change_resource_record_sets(
            HostedZoneId=record["hosted_zone_id"],
            ChangeBatch={
                "Comment": "dns-monitor: WAN IP change",
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": name,
                            "Type": record.get("type", "A"),
                            "TTL": record.get("ttl", 300),
                            "ResourceRecords": [{"Value": ip}],
                        },
                    }
                ],
            },
        )

    def get_record(self, record: dict) -> dict | None:
        """Look up the live ResourceRecordSet for `record`, or None if it doesn't exist."""
        name = fqdn(record)
        rtype = record.get("type", "A")

        resp = self.client.list_resource_record_sets(
            HostedZoneId=record["hosted_zone_id"],
            StartRecordName=name,
            StartRecordType=rtype,
            MaxItems="1",
        )
        for rr in resp.get("ResourceRecordSets", []):
            if _normalize_name(rr["Name"]) == name and rr["Type"] == rtype:
                return rr
        return None

    def _iter_hosted_zones(self):
        """
        Enumerate all hosted zones via ListHostedZonesByName rather than the
        plain ListHostedZones - some accounts' IAM policies grant the former
        (it's what single-domain lookups use) but not the latter.
        """
        kwargs = {}
        while True:
            resp = self.client.list_hosted_zones_by_name(**kwargs)
            yield from resp["HostedZones"]
            if not resp.get("IsTruncated"):
                return
            kwargs = {"DNSName": resp["NextDNSName"], "HostedZoneId": resp["NextHostedZoneId"]}

    def find_a_records_by_value(self, ip: str) -> list[dict]:
        """Find every A record across all hosted zones in this account whose value is `ip`."""
        matches = []
        for zone in self._iter_hosted_zones():
            zone_id = zone["Id"].removeprefix("/hostedzone/")
            zone_domain = zone["Name"].rstrip(".")

            record_paginator = self.client.get_paginator("list_resource_record_sets")
            for record_page in record_paginator.paginate(HostedZoneId=zone_id):
                for rr in record_page["ResourceRecordSets"]:
                    if rr["Type"] != "A":
                        continue
                    values = [v["Value"] for v in rr.get("ResourceRecords", [])]
                    if ip not in values:
                        continue
                    matches.append(
                        {
                            "zone_id": zone_id,
                            "zone_domain": zone_domain,
                            "name": _normalize_name(rr["Name"]),
                            "ttl": rr.get("TTL"),
                        }
                    )
        return matches

    def delete_record(self, record: dict) -> bool:
        """Delete `record` from Route53 if it exists. Returns False if it wasn't found."""
        existing = self.get_record(record)
        if existing is None:
            return False

        self.client.change_resource_record_sets(
            HostedZoneId=record["hosted_zone_id"],
            ChangeBatch={
                "Comment": "dns-monitor: record removed",
                "Changes": [{"Action": "DELETE", "ResourceRecordSet": existing}],
            },
        )
        return True
