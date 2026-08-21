"""Provider-neutral LLM adapter.

Reads whichever key is present in the environment or a local .env, so the same
code runs on a free Groq/Gemini tier or a paid Anthropic/OpenAI key. When no
key is configured ``get_provider`` returns None and the pipeline runs
deterministically -- the model layer is an upgrade, never a dependency.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

_ENV_LOADED = False


def load_dotenv(path: str = ".env") -> None:
    global _ENV_LOADED
    if _ENV_LOADED or not os.path.exists(path):
        _ENV_LOADED = True
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    _ENV_LOADED = True


PROVIDERS = {
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions",
             "llama-3.3-70b-versatile"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions",
               "gpt-4o-mini"),
    "gemini": ("GEMINI_API_KEY",
               "https://generativelanguage.googleapis.com/v1beta/models/"
               "gemini-2.0-flash:generateContent", "gemini-2.0-flash"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages",
                  "claude-sonnet-5"),
}

SYSTEM = (
    "You extract product attributes for an industrial distributor's catalogue.\n"
    "RULES:\n"
    "1. Only report a value if the exact supporting substring appears in the "
    "description. Quote it in `evidence`.\n"
    "2. Never infer, never guess, never fill from world knowledge.\n"
    "3. If nothing new can be extracted, return an empty list.\n"
    "4. Do not repeat attributes listed under `known`.\n"
    "Return strict JSON: {\"facts\":[{\"key\":\"snake_case\",\"label\":\"Title Case\","
    "\"value\":\"...\",\"uom\":\"\",\"evidence\":\"exact substring\","
    "\"confidence\":0.0}]}"
)


def _post(url: str, payload: Dict[str, Any], headers: Dict[str, str],
          timeout: int = 45) -> Dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers=dict({"Content-Type": "application/json"}, **headers))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_json(text: str) -> Dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"facts": []}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"facts": []}


def get_provider(name: str = "") -> Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]:
    load_dotenv()
    order = [name] if name else list(PROVIDERS)
    for prov in order:
        cfg = PROVIDERS.get(prov)
        if not cfg:
            continue
        env_key, url, model = cfg
        key = os.environ.get(env_key)
        if not key:
            continue

        def call(payload: Dict[str, Any], _p=prov, _k=key, _u=url, _m=model
                 ) -> Dict[str, Any]:
            user = ("Description: {}\nUnclaimed text: {}\nKnown: {}"
                    .format(payload.get("description", ""),
                            payload.get("residual", ""),
                            json.dumps(payload.get("known", {}))))
            if _p == "gemini":
                body = {"contents": [{"parts": [{"text": SYSTEM + "\n\n" + user}]}],
                        "generationConfig": {"temperature": 0,
                                             "responseMimeType": "application/json"}}
                data = _post("{}?key={}".format(_u, _k), body, {})
                txt = data["candidates"][0]["content"]["parts"][0]["text"]
            elif _p == "anthropic":
                body = {"model": _m, "max_tokens": 1024, "system": SYSTEM,
                        "temperature": 0,
                        "messages": [{"role": "user", "content": user}]}
                data = _post(_u, body, {"x-api-key": _k,
                                        "anthropic-version": "2023-06-01"})
                txt = data["content"][0]["text"]
            else:
                body = {"model": _m, "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": user}]}
                data = _post(_u, body, {"Authorization": "Bearer " + _k})
                txt = data["choices"][0]["message"]["content"]
            return _extract_json(txt)

        call.name = "{} ({})".format(prov, model)   # type: ignore[attr-defined]
        return call
    return None
