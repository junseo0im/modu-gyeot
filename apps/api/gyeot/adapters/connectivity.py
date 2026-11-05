"""Explicit, bounded connection probes. Never print request URLs or responses."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

FOOD_BASE = "https://openapi.foodsafetykorea.go.kr/api"
GATEWAY = "https://gateway.aitestbed.kr/v1/chat/completions"
SERVICES = ("I0030", "I2710", "I1250")


class ProbeError(Exception):
    """Only static error codes may leave the transport layer."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(request):
    try:
        with build_opener(NoRedirect).open(request, timeout=20) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ProbeError("RESPONSE_TOO_LARGE")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ProbeError("INVALID_RESPONSE")
            return result
    except HTTPError as error:
        code = error.code
        error.close()
        raise ProbeError(f"HTTP_{code}") from None
    except (URLError, TimeoutError, OSError):
        raise ProbeError("NETWORK_ERROR") from None
    except (ValueError, UnicodeError):
        raise ProbeError("INVALID_RESPONSE") from None


def probe_food(settings, service, transport=request_json):
    if service not in SERVICES:
        raise ValueError("Unsupported service")
    if not settings.food_api_key:
        return {"service": service, "status": "KEY_NOT_CONFIGURED"}
    url = f"{FOOD_BASE}/{quote(settings.food_api_key, safe='')}/{service}/json/1/1"
    try:
        data = transport(Request(url, headers={"Accept": "application/json"}))
        payload = data.get(service, data)
        if not isinstance(payload, dict) or not isinstance(payload.get("RESULT"), dict):
            raise ProbeError("INVALID_RESPONSE")
        code = payload["RESULT"].get("CODE")
        if code == "INFO-200":
            return {"service": service, "status": "NO_DATA"}
        if code != "INFO-000":
            return {"service": service, "status": "API_REJECTED"}
        rows = payload.get("row")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProbeError("INVALID_RESPONSE")
        return {"service": service, "status": "OK", "row_count": len(rows)}
    except ProbeError as error:
        return {"service": service, "status": str(error)}


def probe_gateway(settings, transport=request_json):
    if not settings.ai_gateway_api_key:
        return {"service": "AI_GATEWAY", "status": "KEY_NOT_CONFIGURED"}
    payload = {"model": settings.model, "max_tokens": 32,
               "messages": [{"role": "user", "content": "Connection test. Reply only with OK."}]}
    request = Request(GATEWAY, data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Authorization": "Bearer " + settings.ai_gateway_api_key,
                               "Content-Type": "application/json"})
    try:
        data = transport(request)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProbeError("INVALID_RESPONSE")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProbeError("INVALID_RESPONSE")
        result = {"service": "AI_GATEWAY", "status": "OK", "text_response_received": True}
        usage = data.get("usage", {})
        if isinstance(usage, dict):
            result["usage"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                               if type(usage.get(key)) is int and usage[key] >= 0}
        return result
    except ProbeError as error:
        return {"service": "AI_GATEWAY", "status": str(error)}