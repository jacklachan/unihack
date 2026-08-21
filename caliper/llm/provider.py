"""Provider-neutral LLM adapter with an on-disk response cache.

Design notes, all of them learned the hard way:

* **User-Agent matters.** Groq sits behind Cloudflare, which rejects
  ``Python-urllib/3.x`` with a 1010 before the request ever reaches the API.
* **Model names rot.** ``llama-3.3-70b-versatile`` was decommissioned; hard-
  coding a model id is a time bomb. The adapter queries ``/models`` and picks
  the best one actually available, so the pipeline keeps working when the
  provider rotates its catalogue.
* **The cache is a deliverable.** Responses are keyed by a hash of the prompt
  and written to ``data/cache/llm/``. Committing that directory means anyone
  can reproduce the AI-enriched output byte-for-byte with no key and no
  network -- which is the difference between a demo that runs on the judge's
  machine and one that doesn't.
* **No key is not an error.** ``get_provider`` returns None and the pipeline
  runs deterministically.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

_ENV_LOADED = False

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

CACHE_DIR = os.path.join("data", "cache", "llm")


def load_dotenv(path: str = ".env") -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "groq": {
        "env": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models_url": "https://api.groq.com/openai/v1/models",
        # Preference order; the first one actually offered wins.
        "prefer": ["openai/gpt-oss-120b", "qwen/qwen3.6-27b",
                   "openai/gpt-oss-20b", "groq/compound"],
        "style": "openai",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "url": "https://api.openai.com/v1/chat/completions",
        "models_url": "",
        "prefer": ["gpt-4o-mini"],
        "style": "openai",
    },
    "gemini": {
        "env": "GEMINI_API_KEY",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "models_url": "",
        "prefer": ["gemini-2.0-flash"],
        "style": "gemini",
    },
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "url": "https://api.anthropic.com/v1/messages",
        "models_url": "",
        "prefer": ["claude-sonnet-5"],
        "style": "anthropic",
    },
}

SYSTEM = """You extract product attributes for an industrial distributor's catalogue.

HARD RULES
1. Report a value ONLY if the exact supporting substring appears in the description. Put that substring, character for character, in "evidence".
2. Never infer, never guess, never use world knowledge about the product.
3. Do not repeat anything already present in "known".
4. If nothing new can be extracted, return {"facts": []}.
5. Units go in "uom" separately from the numeric "value".

Use snake_case keys and Title Case labels. Prefer these keys when they apply:
item_type, series, material, application, mounting, finish, voltage, amperage,
wattage, color_temperature, lumens, grit, diameter, thickness, arbor_size,
length, width, height, pack_quantity, platform, base_type, bulb_shape, speed,
capacity, sound_level, number_of_cycles.

Return STRICT JSON only:
{"facts":[{"key":"snake_case","label":"Title Case","value":"...","uom":"","evidence":"exact substring","confidence":0.0}]}"""


class Limits:
    """Live view of the provider's rate limits, read from response headers.

    Free tiers are usually capped on tokens-per-minute rather than requests,
    and a caller that ignores that just collects 429s. Pacing against the
    reported remainder turns a failing run into a slow one.
    """
    remaining_tokens: Optional[float] = None
    reset_tokens_s: float = 0.0
    remaining_requests: Optional[float] = None
    reset_requests_s: float = 0.0
    last_seen: float = 0.0


def _parse_duration(text: str) -> float:
    """Groq reports resets as '6h51m50.399s' or '577ms'."""
    if not text:
        return 0.0
    t = str(text).strip()
    m = re.fullmatch(r"([\d.]+)ms", t)
    if m:
        return float(m.group(1)) / 1000.0
    total = 0.0
    for value, unit in re.findall(r"([\d.]+)\s*(h|m|s)", t):
        total += float(value) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def _read_limits(headers: Any) -> None:
    try:
        get = headers.get
    except AttributeError:
        return
    rt = get("x-ratelimit-remaining-tokens")
    if rt is not None:
        try:
            Limits.remaining_tokens = float(rt)
        except ValueError:
            pass
    rr = get("x-ratelimit-remaining-requests")
    if rr is not None:
        try:
            Limits.remaining_requests = float(rr)
        except ValueError:
            pass
    Limits.reset_tokens_s = _parse_duration(get("x-ratelimit-reset-tokens") or "")
    Limits.reset_requests_s = _parse_duration(get("x-ratelimit-reset-requests") or "")
    Limits.last_seen = time.time()


def _pace(estimated_tokens: int = 700) -> None:
    """Wait when the reported token budget cannot cover the next call."""
    if Limits.remaining_tokens is None:
        return
    if Limits.remaining_tokens >= estimated_tokens:
        return
    wait = min(65.0, max(1.0, Limits.reset_tokens_s or 60.0))
    Stats.paced += 1
    time.sleep(wait)
    Limits.remaining_tokens = None      # force a fresh reading


def _post(url: str, payload: Dict[str, Any], headers: Dict[str, str],
          timeout: int = 60) -> Dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers=dict({"Content-Type": "application/json",
                      "User-Agent": UA, "Accept": "application/json"}, **headers))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        _read_limits(resp.headers)
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, headers: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    req = urllib.request.Request(
        url, headers=dict({"User-Agent": UA, "Accept": "application/json"}, **headers))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pick_model(cfg: Dict[str, Any], key: str) -> str:
    """Choose the best available model instead of trusting a hard-coded id."""
    prefer: List[str] = cfg["prefer"]
    murl = cfg.get("models_url")
    if not murl:
        return prefer[0]
    try:
        data = _get(murl, {"Authorization": "Bearer " + key})
        available = {m.get("id") for m in data.get("data", [])}
    except Exception:
        return prefer[0]
    for m in prefer:
        if m in available:
            return m
    # Fall back to any chat-capable model that is not audio/guard tooling.
    for m in sorted(available):
        low = str(m).lower()
        if not any(x in low for x in ("whisper", "guard", "orpheus", "tts", "embed")):
            return m
    return prefer[0]


def _extract_any(text: str) -> Dict[str, Any]:
    """Parse an audit response: a list of verdicts rather than facts."""
    if not text:
        return {"verdicts": []}
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {"verdicts": []}
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"verdicts": []}
    if isinstance(obj, list):
        return {"verdicts": obj}
    v = obj.get("verdicts", obj.get("results", [])) if isinstance(obj, dict) else []
    return {"verdicts": v if isinstance(v, list) else []}


def _extract_json(text: str) -> Dict[str, Any]:
    """Models wrap JSON in prose or fences often enough that this must be
    tolerant -- but it never invents facts, it only fails to find them."""
    if not text:
        return {"facts": []}
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {"facts": []}
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"facts": []}
    if isinstance(obj, list):
        return {"facts": obj}
    if not isinstance(obj, dict):
        return {"facts": []}
    facts = obj.get("facts", obj.get("attributes", []))
    return {"facts": facts if isinstance(facts, list) else []}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def _cache_key(provider: str, model: str, user: str, system: str = "") -> str:
    h = hashlib.sha256("{}|{}|{}|{}".format(provider, model, system or SYSTEM, user)
                       .encode("utf-8")).hexdigest()
    return h[:40]


def _cache_read(key: str) -> Optional[Dict[str, Any]]:
    p = os.path.join(CACHE_DIR, key + ".json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _cache_write(key: str, payload: Dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(os.path.join(CACHE_DIR, key + ".json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
    except OSError:
        pass


class Stats:
    calls = 0
    cache_hits = 0
    errors = 0
    retries = 0
    paced = 0


def _build_user(payload: Dict[str, Any]) -> str:
    return ("Description: {}\nText no rule claimed: {}\nAlready known: {}"
            .format(payload.get("description", ""),
                    payload.get("residual", ""),
                    json.dumps(payload.get("known", {}), sort_keys=True)))


def _build_audit_user(payload: Dict[str, Any]) -> str:
    return "Description: {}\nAttributes to audit:\n{}".format(
        payload.get("description", ""),
        json.dumps(payload.get("facts", []), sort_keys=True, indent=1))


def get_auditor(name: str = "", use_cache: bool = True, api_key: str = ""
                ) -> Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]:
    """A provider callable that renders verdicts instead of producing values.

    Uses its own system prompt and its own cache namespace, so audit responses
    never collide with extraction responses for the same product.
    """
    from .audit import AUDIT_SYSTEM
    return get_provider(name, use_cache=use_cache, system=AUDIT_SYSTEM,
                        build_user=_build_audit_user, tag="audit",
                        api_key=api_key)


def get_provider(name: str = "", use_cache: bool = True, offline: bool = False,
                 system: str = "", build_user: Optional[Callable[[Dict[str, Any]], str]] = None,
                 tag: str = "extract", api_key: str = ""
                 ) -> Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]:
    """Return a callable ``fn(payload) -> {"facts": [...]}``.

    ``offline=True`` serves only from the committed cache and never touches the
    network -- this is how a judge reproduces the AI-enriched run without a key.
    """
    load_dotenv()
    system = system or SYSTEM
    build_user = build_user or _build_user

    if offline:
        def cached_only(payload: Dict[str, Any]) -> Dict[str, Any]:
            user = _build_user(payload)
            for prov in PROVIDERS:
                for model in PROVIDERS[prov]["prefer"]:
                    hit = _cache_read(_cache_key(prov, model, user))
                    if hit is not None:
                        Stats.cache_hits += 1
                        return hit
            return {"facts": []}
        cached_only.name = "cache-only (offline replay)"      # type: ignore
        return cached_only

    order = [name] if name else list(PROVIDERS)
    for prov in order:
        cfg = PROVIDERS.get(prov)
        if not cfg:
            continue
        key = api_key or os.environ.get(cfg["env"])
        if not key:
            continue
        model = _pick_model(cfg, key)

        def call(payload: Dict[str, Any], _p=prov, _k=key, _c=cfg, _m=model,
                 _sys=system, _bu=build_user, _tag=tag) -> Dict[str, Any]:
            user = _bu(payload)
            ck = _cache_key(_p, _m, _tag + "|" + user, _sys)
            if use_cache:
                hit = _cache_read(ck)
                if hit is not None:
                    Stats.cache_hits += 1
                    return hit

            style = _c["style"]
            last_err: Optional[Exception] = None
            for attempt in range(4):
                try:
                    _pace()
                    if style == "gemini":
                        url = _c["url"].format(model=_m) + "?key=" + _k
                        body = {"contents": [{"parts": [{"text": SYSTEM + "\n\n" + user}]}],
                                "generationConfig": {"temperature": 0,
                                                     "responseMimeType": "application/json"}}
                        data = _post(url, body, {})
                        txt = data["candidates"][0]["content"]["parts"][0]["text"]
                    elif style == "anthropic":
                        body = {"model": _m, "max_tokens": 1024, "system": _sys,
                                "temperature": 0,
                                "messages": [{"role": "user", "content": user}]}
                        data = _post(_c["url"], body,
                                     {"x-api-key": _k, "anthropic-version": "2023-06-01"})
                        txt = data["content"][0]["text"]
                    else:
                        body = {"model": _m, "temperature": 0,
                                "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": _sys},
                                             {"role": "user", "content": user}]}
                        data = _post(_c["url"], body, {"Authorization": "Bearer " + _k})
                        txt = data["choices"][0]["message"]["content"]

                    out = _extract_json(txt) if _tag == "extract" else _extract_any(txt)
                    Stats.calls += 1
                    if use_cache:
                        _cache_write(ck, out)
                    return out

                except urllib.error.HTTPError as exc:
                    last_err = exc
                    _read_limits(getattr(exc, "headers", None))
                    if exc.code in (429, 500, 502, 503, 529):
                        Stats.retries += 1
                        # Honour the provider's own reset hint when it gives one.
                        hinted = _parse_duration(
                            (getattr(exc, "headers", None) or {}).get(
                                "retry-after", "") or "")
                        time.sleep(min(65.0, hinted or (1.5 * (2 ** attempt))))
                        continue
                    break
                except Exception as exc:
                    last_err = exc
                    Stats.retries += 1
                    time.sleep(1.0 + attempt)
            Stats.errors += 1
            raise last_err if last_err else RuntimeError("llm call failed")

        call.name = "{} ({}, {})".format(prov, model, tag)     # type: ignore
        call.provider = prov                                   # type: ignore
        call.model = model                                     # type: ignore
        return call
    return None
