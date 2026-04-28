import requests

from pi_identity import registration_payload


def post_status(cfg, state, message="", source="agent", timeout=5, **extra):
    try:
        _cfg, _changed, payload = registration_payload(dict(cfg))
        payload.update(
            {
                "state": str(state or "").strip(),
                "message": str(message or "").strip(),
                "source": str(source or "").strip() or "agent",
            }
        )
        for key, value in (extra or {}).items():
            if value not in (None, ""):
                payload[key] = value
        requests.post(cfg["server"].rstrip("/") + "/status", json=payload, timeout=timeout)
        return True
    except Exception:
        return False
