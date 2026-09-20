import boto3

from dns_monitor.records import fqdn


class Route53Provider:
    def __init__(self, region: str = None, **_ignored):
        self.client = boto3.client("route53", region_name=region)

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
