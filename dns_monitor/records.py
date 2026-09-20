def fqdn(record: dict) -> str:
    name = record["name"]
    domain = record["domain"]
    if name in ("@", "", None):
        return domain
    return f"{name}.{domain}"
