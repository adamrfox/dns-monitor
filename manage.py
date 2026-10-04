#!./.venv/bin/python3
"""
Add or remove a dns-monitor managed DNS record, applying the change to
Route53 immediately instead of waiting for the next WAN IP change (or having
to remember the state.json/force-resync dance).

    manage.py add    --domain example.com --name vpn --hosted-zone-id Z123...
    manage.py remove --domain example.com --name vpn
    manage.py list
    manage.py scan
"""
import argparse
import sys

from ruamel.yaml import YAML

from dns_monitor.providers.route53 import Route53Error, Route53Provider
from dns_monitor.records import fqdn, relative_name
from dns_monitor.unifi import UnifiClient

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.load(f)


def save_config(path: str, config: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(config, f)


def find_record(records: list, domain: str, name: str, rtype: str):
    for r in records:
        if r["domain"] == domain and r["name"] == name and r.get("type", "A") == rtype:
            return r
    return None


def cmd_add(args) -> None:
    config = load_config(args.config)
    records = config["records"]

    if find_record(records, args.domain, args.name, args.type):
        print(f"{args.name}.{args.domain} ({args.type}) is already in {args.config}", file=sys.stderr)
        sys.exit(1)

    route53 = Route53Provider(**config.get("route53", {}))

    hosted_zone_id = args.hosted_zone_id
    if hosted_zone_id is None:
        try:
            hosted_zone_id = route53.find_hosted_zone_id(args.domain)
        except Route53Error as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    record = {
        "domain": args.domain,
        "name": args.name,
        "type": args.type,
        "ttl": args.ttl,
        "hosted_zone_id": hosted_zone_id,
    }

    unifi = UnifiClient(**config["unifi"])
    current_ip = unifi.get_wan_ip()

    route53.update_record(record, current_ip)
    print(f"Created {fqdn(record)} ({args.type}) -> {current_ip} in Route53")

    records.append(record)
    save_config(args.config, config)
    print(f"Added to {args.config}")


def cmd_remove(args) -> None:
    config = load_config(args.config)
    records = config["records"]

    record = find_record(records, args.domain, args.name, args.type)
    if record is None:
        print(f"{args.name}.{args.domain} ({args.type}) is not in {args.config}", file=sys.stderr)
        sys.exit(1)

    route53 = Route53Provider(**config.get("route53", {}))
    if route53.delete_record(record):
        print(f"Deleted {fqdn(record)} ({args.type}) from Route53")
    else:
        print(f"No live record found in Route53 for {fqdn(record)} ({args.type}) - nothing to delete there")

    records.remove(record)
    save_config(args.config, config)
    print(f"Removed from {args.config}")


def cmd_list(args) -> None:
    config = load_config(args.config)
    records = config["records"]

    if not records:
        print(f"No records in {args.config}")
        return

    name_width = max(len(fqdn(r)) for r in records)
    for r in records:
        rtype = r.get("type", "A")
        ttl = r.get("ttl", 300)
        print(f"{fqdn(r):<{name_width}}  {rtype:<6}TTL={ttl:<6}{r['hosted_zone_id']}")


def cmd_scan(args) -> None:
    config = load_config(args.config)
    tracked = {(r["domain"], r["name"], r.get("type", "A")) for r in config["records"]}

    unifi = UnifiClient(**config["unifi"])
    current_ip = unifi.get_wan_ip()
    print(f"Current WAN IP: {current_ip}")

    route53 = Route53Provider(**config.get("route53", {}))
    matches = route53.find_a_records_by_value(current_ip)

    untracked = []
    for m in matches:
        try:
            name = relative_name(m["name"], m["zone_domain"])
        except ValueError:
            continue
        if (m["zone_domain"], name, "A") not in tracked:
            untracked.append((m["zone_domain"], name, m["zone_id"], m["ttl"]))

    if not untracked:
        print(f"No untracked A records found pointing at {current_ip}")
        return

    print(f"\nFound {len(untracked)} A record(s) pointing at {current_ip} not in {args.config}:\n")
    for domain, name, zone_id, ttl in untracked:
        shown_fqdn = domain if name == "@" else f"{name}.{domain}"
        print(f"  {shown_fqdn}  (TTL={ttl}, zone={zone_id})")
        print(f"    manage.py add --domain {domain} --name {name} --hosted-zone-id {zone_id}")


def main():
    parser = argparse.ArgumentParser(description="Add or remove a dns-monitor managed DNS record.")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="Create a record in Route53 with the current WAN IP and save it to config.yaml")
    add_p.add_argument("--domain", required=True)
    add_p.add_argument("--name", required=True, help='"@" for apex, "*" for wildcard, or a subdomain label')
    add_p.add_argument(
        "--hosted-zone-id",
        default=None,
        help="Only needed if --domain has more than one hosted zone in Route53 (auto-resolved otherwise)",
    )
    add_p.add_argument("--type", default="A")
    add_p.add_argument("--ttl", type=int, default=300)
    add_p.set_defaults(func=cmd_add)

    remove_p = sub.add_parser("remove", help="Delete a record from Route53 and remove it from config.yaml")
    remove_p.add_argument("--domain", required=True)
    remove_p.add_argument("--name", required=True)
    remove_p.add_argument("--type", default="A")
    remove_p.set_defaults(func=cmd_remove)

    list_p = sub.add_parser("list", help="List the records currently in config.yaml")
    list_p.set_defaults(func=cmd_list)

    scan_p = sub.add_parser(
        "scan", help="Scan all Route53 hosted zones for A records pointing at the current WAN IP not in config.yaml"
    )
    scan_p.set_defaults(func=cmd_scan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
