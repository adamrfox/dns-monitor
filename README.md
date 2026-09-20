# dns-monitor

Watches a UniFi router's WAN IP and keeps a set of AWS Route53 A records in
sync with it. Built for a home network with a dynamic IP where a handful of
personal domains/subdomains need to keep pointing at it.

## How it works

- Polls a UniFi OS console's local Integration API for the current WAN IP.
- Compares it to the last-known IP (`state.json`).
- On change, `UPSERT`s every record listed in `config.yaml` in Route53.
- Optionally pushes a heartbeat to an Uptime Kuma "Push" monitor on every run.
- Runs on a schedule via a systemd user timer (default: every 5 minutes).

Only records explicitly listed in `config.yaml` are ever touched - nothing is
auto-discovered from Route53, so there's no risk of it reaching into a record
that isn't meant to track the WAN IP.

## Prerequisites

- Python 3.10+
- A UniFi OS console (UDM-class device) with Network application 9.3+, so
  Settings > Control Plane > Integrations offers "Create API Key"
- An AWS account with a Route53 hosted zone for each domain you want to manage
- (Optional) An Uptime Kuma instance, for alerting

## Setup

### 1. Clone and install dependencies

```sh
git clone https://github.com/adamrfox/dns-monitor.git
cd dns-monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Create a UniFi API key

1. Log into your UniFi console's web UI.
2. Settings > Control Plane > Integrations > Create API Key.
3. Copy the generated key.

Username/password auth is **not** supported here - if your account has 2FA
enabled, the API has no way to satisfy the interactive verification step, so
the API key is the only auth path this project implements.

### 3. Set up AWS credentials

Create an IAM user with API access only (no console login) and attach an
inline policy scoped to Route53:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "route53:*",
      "Resource": "*"
    }
  ]
}
```

Generate an access key for that user, then configure it via any method
`boto3`'s standard credential chain supports - `aws configure`, environment
variables, or an IAM role.

### 4. Configure dns-monitor

```sh
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

- `unifi.controller_url` - your console's URL, e.g. `https://192.168.1.1`
  (no port needed on a UniFi OS console)
- `unifi.site` - usually `default`
- `unifi.auth.api_key` - the key from step 2
- `route53.region` - any valid AWS region (Route53 itself is global, but
  boto3 still wants one, e.g. `us-east-1`)
- `records` - every record to keep in sync: `domain`, `name` (`@` for the
  apex, `*` for a wildcard, or a subdomain label), `type`, `ttl`, and the
  Route53 `hosted_zone_id` it lives in
- `uptime_kuma.push_url` (optional) - see step 7

`config.yaml` is gitignored. It holds real credentials - never commit it.

### 5. Test it

```sh
.venv/bin/python3 -m dns_monitor.main --config config.yaml --dry-run -v
```

Logs what it would do without touching Route53 or writing state.

Run for real:

```sh
.venv/bin/python3 -m dns_monitor.main --config config.yaml
```

### 6. Schedule it (systemd user timer)

```sh
mkdir -p ~/.config/systemd/user
cp systemd/dns-monitor.service systemd/dns-monitor.timer ~/.config/systemd/user/
```

Edit the copied `dns-monitor.service` if your clone path or venv location
differs from the defaults it ships with.

```sh
systemctl --user daemon-reload
systemctl --user enable --now dns-monitor.timer
loginctl enable-linger "$USER"   # keeps it running after logout/reboot, no root needed
```

```sh
systemctl --user status dns-monitor.timer      # confirm it's scheduled
systemctl --user start dns-monitor.service     # trigger a run immediately
```

### 7. Alerting via Uptime Kuma (optional)

1. Add a new monitor in Kuma, type **Push**.
2. Set its heartbeat interval with some slack around your actual run
   interval (e.g. 300s interval + 2 retries works well for a 5-minute timer).
3. Attach whatever notification channels you already use.
4. Copy the generated push URL into `config.yaml`'s `uptime_kuma.push_url`.

dns-monitor reports `status=up` on every successful run (including "no
change") and `status=down` with the error on failure. If dns-monitor stops
running entirely - crashed, timer disabled, host down - Kuma's own
missed-heartbeat detection catches that too, without needing to hear from
this project at all.

## Notes

- Route53 updates use `UPSERT`, so re-running with an unchanged IP is a no-op.
- If any record fails to update, state is not saved, so the next run retries
  every record rather than drifting into a partially-updated state.
