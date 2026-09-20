import argparse
import logging

from dns_monitor.config import load_config
from dns_monitor.notify import push_heartbeat
from dns_monitor.providers.route53 import Route53Provider
from dns_monitor.records import fqdn
from dns_monitor.state import load_state, save_state
from dns_monitor.unifi import UnifiClient

log = logging.getLogger("dns-monitor")


def run(config_path: str, dry_run: bool) -> None:
    config = load_config(config_path)
    push_url = config.get("uptime_kuma", {}).get("push_url")

    try:
        _run(config, dry_run, push_url)
    except Exception as e:
        log.exception("dns-monitor run failed")
        if push_url and not dry_run:
            push_heartbeat(push_url, "down", f"Error: {e}")
        raise


def _run(config: dict, dry_run: bool, push_url: str | None) -> None:
    state = load_state(config["state_file"])

    unifi = UnifiClient(**config["unifi"])
    current_ip = unifi.get_wan_ip()

    if current_ip == state.get("last_ip"):
        log.info("WAN IP unchanged (%s)", current_ip)
        if push_url and not dry_run:
            push_heartbeat(push_url, "up", f"WAN IP unchanged ({current_ip})")
        return

    log.info("WAN IP changed: %s -> %s", state.get("last_ip"), current_ip)
    route53 = Route53Provider(**config.get("route53", {}))

    any_failed = False
    for record in config["records"]:
        name = fqdn(record)

        if dry_run:
            log.info("[dry-run] would update %s -> %s", name, current_ip)
            continue

        try:
            route53.update_record(record, current_ip)
            log.info("Updated %s -> %s", name, current_ip)
        except Exception:
            log.exception("Failed to update %s", name)
            any_failed = True

    if dry_run:
        return

    if any_failed:
        log.warning("Some records failed to update - not saving new state, will retry next run")
        if push_url:
            push_heartbeat(push_url, "down", f"Some record(s) failed updating to {current_ip}")
        return

    state["last_ip"] = current_ip
    save_state(config["state_file"], state)
    if push_url:
        push_heartbeat(push_url, "up", f"Updated {len(config['records'])} record(s) to {current_ip}")


def main():
    parser = argparse.ArgumentParser(description="Sync DNS A records to the current Unifi WAN IP.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Log what would change without updating DNS")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    run(args.config, args.dry_run)


if __name__ == "__main__":
    main()
