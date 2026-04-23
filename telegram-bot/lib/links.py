"""Build VLESS Reality + Hysteria2 share-link URIs from credentials + IP."""

from __future__ import annotations

from urllib.parse import quote


def _enc(s: str) -> str:
    return quote(s, safe="")


def vless_link(*, host: str, uuid: str, public_key: str, sni: str, short_id: str,
               flow: str = "xtls-rprx-vision", remark: str = "DIY-VPN Reality") -> str:
    return (
        f"vless://{uuid}@{host}:443"
        f"?security=reality&encryption=none"
        f"&pbk={public_key}&fp=chrome&type=tcp"
        f"&flow={flow}&sni={sni}&sid={short_id}"
        f"#{_enc(remark)}"
    )


def hysteria2_link(*, host: str, password: str, obfs_password: str,
                   sni: str = "bing.com", remark: str = "DIY-VPN Hysteria2") -> str:
    return (
        f"hysteria2://{_enc(password)}@{host}:443/"
        f"?obfs=salamander&obfs-password={_enc(obfs_password)}"
        f"&sni={sni}&insecure=1"
        f"#{_enc(remark)}"
    )


def host_for(ip: str) -> str:
    """Wraps IPv6 in brackets, leaves IPv4 alone."""
    return f"[{ip}]" if ":" in ip else ip
