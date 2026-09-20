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
