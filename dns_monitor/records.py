def fqdn(record: dict) -> str:
    name = record["name"]
    domain = record["domain"]
    if name in ("@", "", None):
        return domain
    return f"{name}.{domain}"


def relative_name(full_name: str, domain: str) -> str:
    """Inverse of fqdn(): e.g. ("vpn.example.com", "example.com") -> "vpn"."""
    domain = domain.rstrip(".")
    full_name = full_name.rstrip(".")
    if full_name == domain:
        return "@"
    suffix = "." + domain
    if full_name.endswith(suffix):
        return full_name[: -len(suffix)]
    raise ValueError(f"{full_name!r} is not under domain {domain!r}")
