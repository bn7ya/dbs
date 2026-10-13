from __future__ import annotations

import ipaddress

from django.utils.crypto import salted_hmac

MINIMUM_PREFIX = {4: 8, 6: 16}

STORED_PREFIX = {4: 24, 6: 48}

ADDRESS_SALT = "dbs.security.address"


def parse_address(text):
    candidate = str(text or "").strip()
    if not candidate:
        return None
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def parse_networks(raw):
    if isinstance(raw, (list, tuple, set, frozenset)):
        raw = "\n".join(str(entry) for entry in raw)
    if not isinstance(raw, str):
        return []
    found = []
    for line in raw.replace(",", "\n").split("\n"):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            network = ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            continue
        if network.prefixlen < MINIMUM_PREFIX[network.version]:
            continue
        found.append(network)
    return found


def contains(networks, address) -> bool:
    parsed = parse_address(address) if isinstance(address, str) else address
    if parsed is None:
        return False
    return any(parsed in network for network in networks)


def stored_prefix(address) -> str:
    parsed = parse_address(address)
    if parsed is None:
        return ""
    length = STORED_PREFIX[parsed.version]
    return str(ipaddress.ip_network(f"{parsed}/{length}", strict=False))


def address_digest(address) -> str:
    parsed = parse_address(address)
    if parsed is None:
        return ""
    return salted_hmac(ADDRESS_SALT, str(parsed), algorithm="sha256").hexdigest()
