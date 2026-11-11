"""Full-featured client for the Outline Server Management API.

The management URL itself is a secret. Keep it only in OUTLINE_API_URL in
the environment; never send it through Telegram or store it in shop.db.
"""
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from config import OUTLINE_API_URL, OUTLINE_API_VERIFY_TLS


def is_configured():
    return bool(OUTLINE_API_URL)


def _request(path, method="GET", payload=None):
    if not is_configured():
        raise RuntimeError("Outline API URL is not configured")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{OUTLINE_API_URL}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    context = None if OUTLINE_API_VERIFY_TLS else ssl._create_unverified_context()
    try:
        with urlopen(request, timeout=12, context=context) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"Outline API HTTP {error.code}: {body}") from error
    except URLError as error:
        raise RuntimeError(f"Outline API connection failed: {error.reason}") from error


def _plan_bytes(item_name):
    """Read a per-key quota such as 100GB or 1TB from the product name."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB)\b", str(item_name), re.I)
    if not match:
        return 0
    multiplier = 1024 ** 4 if match.group(2).upper() == "TB" else 1024 ** 3
    return int(float(match.group(1)) * multiplier)


def create_access_key(item_name, order_code, expiry_date=""):
    """Create a fresh Outline access key on-demand, set quota and name."""
    if not is_configured():
        return {"ok": False, "mode": "manual", "reason": "OUTLINE_API_URL is not configured"}
    try:
        created = _request("/access-keys", method="POST")
        key_id = str(created.get("id") or "")
        access_url = str(created.get("accessUrl") or "")
        if not key_id or not access_url:
            return {"ok": False, "mode": "error", "reason": "Invalid response from Outline server"}
        safe_key_id = quote(key_id, safe="")
        expiry_label = str(expiry_date or "").split(" ", 1)[0]
        label_name = f"ENI | {order_code}" + (f" | Exp {expiry_label}" if expiry_label else "")
        _request(
            f"/access-keys/{safe_key_id}/name", "PUT",
            {"name": label_name[:100]},
        )
        quota_bytes = _plan_bytes(item_name)
        if quota_bytes > 0:
            _request(
                f"/access-keys/{safe_key_id}/data-limit", "PUT",
                {"limit": {"bytes": quota_bytes}},
            )
        tagged_url = f"{access_url}#ENI-{order_code}" if "#" not in access_url else access_url
        return {
            "ok": True,
            "mode": "auto",
            "key_id": key_id,
            "access_url": tagged_url,
            "quota_bytes": quota_bytes,
            "formatted": f"Key ID: {key_id}\n{tagged_url}",
        }
    except Exception as error:
        return {"ok": False, "mode": "error", "reason": str(error)}


def get_key_data_usage(key_id, item_name=""):
    """Fetch current data usage and data limit for an Outline key."""
    if not is_configured():
        return {"ok": False, "reason": "OUTLINE_API_URL is not configured"}
    if not key_id:
        return {"ok": False, "reason": "Outline Key ID is missing for this order"}
    key_id = str(key_id).strip()
    safe_key_id = quote(key_id, safe="")
    try:
        key_info = _request(f"/access-keys/{safe_key_id}")
        transfer = _request("/metrics/transfer")
        used_bytes = int(
            transfer.get("bytesTransferredByUserId", {}).get(key_id, 0) or 0
        )
        limit_obj = key_info.get("dataLimit") or {}
        limit_bytes = int(limit_obj.get("bytes", 0) or 0)
        if not limit_bytes and item_name:
            limit_bytes = _plan_bytes(item_name)
        used_gb = round(used_bytes / (1024 ** 3), 2)
        limit_gb = round(limit_bytes / (1024 ** 3), 2) if limit_bytes > 0 else None
        remaining_gb = round(max(0.0, limit_gb - used_gb), 2) if limit_gb is not None else None
        percent = min(100, int(round((used_bytes / limit_bytes) * 100))) if limit_bytes > 0 else 0
        return {
            "ok": True,
            "key_id": key_id,
            "name": key_info.get("name") or "",
            "used_bytes": used_bytes,
            "limit_bytes": limit_bytes,
            "used_gb": used_gb,
            "limit_gb": limit_gb,
            "remaining_gb": remaining_gb,
            "percent": percent,
        }
    except Exception as error:
        return {"ok": False, "reason": str(error)}


def suspend_access_key(key_id, order_code=""):
    """Temporarily disable an expired key by setting data limit to 0 bytes."""
    if not is_configured():
        return {"ok": False, "mode": "manual", "reason": "OUTLINE_API_URL is not configured"}
    if not key_id:
        return {"ok": False, "mode": "error", "reason": "Outline key ID is missing"}
    safe_key_id = quote(str(key_id).strip(), safe="")
    try:
        _request(
            f"/access-keys/{safe_key_id}/data-limit", "PUT",
            {"limit": {"bytes": 0}},
        )
        if order_code:
            _request(
                f"/access-keys/{safe_key_id}/name", "PUT",
                {"name": f"[EXPIRED] ENI | {order_code}"[:100]},
            )
        return {"ok": True, "mode": "auto"}
    except Exception as error:
        return {"ok": False, "mode": "error", "reason": str(error)}


def delete_access_key(key_id):
    """Permanently delete an Outline access key from the server."""
    if not is_configured():
        return {"ok": False, "mode": "manual", "reason": "OUTLINE_API_URL is not configured"}
    if not key_id:
        return {"ok": False, "mode": "error", "reason": "Outline key ID is missing"}
    safe_key_id = quote(str(key_id).strip(), safe="")
    try:
        _request(f"/access-keys/{safe_key_id}", method="DELETE")
        return {"ok": True, "mode": "auto"}
    except Exception as error:
        return {"ok": False, "mode": "error", "reason": str(error)}


def get_server_status():
    """Return server info, total keys, and total bandwidth transferred."""
    if not is_configured():
        return {"ok": False, "reason": "OUTLINE_API_URL is not configured"}
    try:
        server = _request("/server")
        keys_data = _request("/access-keys")
        transfer = _request("/metrics/transfer")
        keys = keys_data.get("accessKeys") or []
        usage_map = transfer.get("bytesTransferredByUserId") or {}
        total_bytes = sum(int(v or 0) for v in usage_map.values())
        return {
            "ok": True,
            "name": server.get("name") or "Outline Server",
            "version": server.get("version") or "-",
            "port": server.get("portForNewAccessKeys") or "-",
            "total_keys": len(keys),
            "total_gb": round(total_bytes / (1024 ** 3), 2),
        }
    except Exception as error:
        return {"ok": False, "reason": str(error)}


def renew_access_key(key_id, item_name, order_code, expiry_date):
    """Extend quota when relevant and label the existing key with its expiry.

    Outline has no calendar-expiry endpoint. The bot owns that date; Outline
    only receives the quota update and a descriptive key name.
    """
    if not is_configured():
        return {"mode": "manual", "reason": "OUTLINE_API_URL is not configured"}
    if not key_id:
        return {"mode": "error", "reason": "Outline key ID is missing for this order"}

    key_id = str(key_id)
    safe_key_id = quote(key_id, safe="")
    try:
        _request(f"/access-keys/{safe_key_id}")
        quota_bytes = _plan_bytes(item_name)
        if quota_bytes:
            transfer = _request("/metrics/transfer")
            used_bytes = int(
                transfer.get("bytesTransferredByUserId", {}).get(key_id, 0) or 0
            )
            _request(
                f"/access-keys/{safe_key_id}/data-limit", "PUT",
                {"limit": {"bytes": used_bytes + quota_bytes}},
            )
        else:
            # Unlimited plan: remove any data limit (e.g. if previously suspended)
            try:
                _request(f"/access-keys/{safe_key_id}/data-limit", "DELETE")
            except Exception:
                pass
        expiry_label = str(expiry_date or "").split(" ", 1)[0]
        _request(
            f"/access-keys/{safe_key_id}/name", "PUT",
            {"name": f"ENI | {order_code} | Exp {expiry_label}"[:100]},
        )
        return {"mode": "auto", "quota_updated": bool(quota_bytes)}
    except Exception as error:
        return {"mode": "error", "reason": str(error)}


def get_all_keys_with_usage():
    """Return all Outline keys from the server along with each key's usage and data limit."""
    if not is_configured():
        return {"ok": False, "reason": "OUTLINE_API_URL is not configured"}
    try:
        server = _request("/server")
        keys_data = _request("/access-keys")
        transfer = _request("/metrics/transfer")
        keys = keys_data.get("accessKeys") or []
        usage_map = transfer.get("bytesTransferredByUserId") or {}
        enriched_keys = []
        total_bytes = 0
        for k in keys:
            kid = str(k.get("id") or "")
            used_b = int(usage_map.get(kid, 0) or 0)
            total_bytes += used_b
            limit_obj = k.get("dataLimit") or {}
            limit_b = int(limit_obj.get("bytes", 0) or 0)
            used_gb = round(used_b / (1024 ** 3), 2)
            limit_gb = round(limit_b / (1024 ** 3), 2) if limit_b > 0 else None
            rem_gb = round(max(0.0, limit_gb - used_gb), 2) if limit_gb is not None else None
            pct = min(100, int(round((used_b / limit_b) * 100))) if limit_b > 0 else 0
            enriched_keys.append({
                "key_id": kid,
                "name": str(k.get("name") or f"Key #{kid}"),
                "access_url": str(k.get("accessUrl") or ""),
                "used_bytes": used_b,
                "limit_bytes": limit_b,
                "used_gb": used_gb,
                "limit_gb": limit_gb,
                "remaining_gb": rem_gb,
                "percent": pct,
                "is_suspended": (limit_obj != {} and limit_b == 0),
            })
        enriched_keys.sort(key=lambda x: x["used_bytes"], reverse=True)
        return {
            "ok": True,
            "server_name": server.get("name") or "Outline Server",
            "version": server.get("version") or "-",
            "port": server.get("portForNewAccessKeys") or "-",
            "total_keys": len(enriched_keys),
            "total_gb": round(total_bytes / (1024 ** 3), 2),
            "keys": enriched_keys,
        }
    except Exception as error:
        return {"ok": False, "reason": str(error)}
