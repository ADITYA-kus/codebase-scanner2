from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib import error, request

from analysis.graph.callgraph_index import CallGraphIndex, CallSite
from analysis.indexing.symbol_index import SymbolIndex, SymbolInfo
from analysis.utils.cache_manager import get_cache_dir


MAX_SNIPPET_LINES = 80
LLM_CACHE_FILE = "llm_cache.json"

GEMINI_MODEL = "gemini-2.5-flash-lite"
GROQ_MODEL = "llama-3.1-8b-instant"
XAI_DEFAULT_MODEL = "grok-code-fast-1"

SYSTEM_INSTRUCTION = (
    "Output plain text only. No markdown, no headings, no bullets. "
    "Keep total output <=90 words. Use simple developer language. "
    "Use exactly this 3-line structure:\n"
    "1) What it does: 1 sentence.\n"
    "2) Connections: called by <0-2 FQNs>; calls <0-3 FQNs>.\n"
    "3) Notes: <0-3 short notes about risks/pitfalls/design>.\n"
    "If dependencies are empty write: Connections: none"
)

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{8,})['\"]?"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)\b(token|access_token|auth_token)\s*[:=]\s*['\"]?([A-Za-z0-9._\-]{8,})['\"]?"),
    re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\n]{4,})['\"]?"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def _redact(text: str) -> str:
    redacted = text or ""
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def _redact_payload(obj: Any) -> Any:
    if isinstance(obj, str):
        return _redact(obj)
    if isinstance(obj, list):
        return [_redact_payload(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _redact_payload(v) for k, v in obj.items()}
    return obj


def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _collect_python_files(root_dir: str) -> List[str]:
    files: List[str] = []
    for root, _, names in os.walk(root_dir):
        for name in names:
            if name.endswith(".py") and not name.startswith("__"):
                files.append(os.path.join(root, name))
    return files


def _file_to_module(file_path: str, repo_root: str) -> str:
    repo_root = os.path.abspath(repo_root)
    file_path = os.path.abspath(file_path)
    rel = os.path.relpath(file_path, repo_root).replace(os.sep, ".")
    if rel.endswith(".py"):
        rel = rel[:-3]
    repo_name = os.path.basename(repo_root.rstrip("\\/"))
    return f"{repo_name}.{rel}"


def _build_symbol_index(repo_dir: str) -> SymbolIndex:
    idx = SymbolIndex()
    for file_path in _collect_python_files(repo_dir):
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        idx.index_file(tree, _file_to_module(file_path, repo_dir), os.path.abspath(file_path))
    return idx


def _symbol_from_index(symbol_index: SymbolIndex, fqn: str) -> Optional[SymbolInfo]:
    for sym in symbol_index.all_symbols():
        if f"{sym.module}.{sym.qualified_name}" == fqn:
            return sym
    return None


def _build_callgraph(resolved_calls_path: str) -> CallGraphIndex:
    calls = _load_json(resolved_calls_path, [])
    idx = CallGraphIndex()
    for c in calls:
        idx.add_call(
            CallSite(
                caller_fqn=c.get("caller_fqn", ""),
                callee_fqn=c.get("callee_fqn"),
                callee_name=c.get("callee", "<unknown>"),
                file=c.get("file", ""),
                line=int(c.get("line", -1)),
            )
        )
    return idx


def _extract_snippet(file_path: str, start_line: int, end_line: int) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    n = len(lines)
    start = max(1, start_line - 20)
    end = min(n, end_line + 20)
    selected = lines[start - 1:end]
    if len(selected) > MAX_SNIPPET_LINES:
        selected = selected[:MAX_SNIPPET_LINES]
    return "".join(selected)


def _extract_signature_returns_docstring(explain_item: Dict[str, Any]) -> Dict[str, str]:
    signature = ""
    returns = ""
    docstring = explain_item.get("docstring", "")
    for line in explain_item.get("details", []):
        if isinstance(line, str) and line.startswith("Signature:"):
            signature = line.replace("Signature:", "", 1).strip()
        if isinstance(line, str) and line.startswith("Returns:"):
            returns = line.strip()
    return {
        "signature": signature,
        "returns": returns,
        "docstring": docstring,
    }


def build_symbol_context(fqn: str, repo_dir: str) -> Dict[str, Any]:
    repo_dir = os.path.abspath(repo_dir)
    cache_dir = get_cache_dir(repo_dir)
    explain_path = os.path.join(cache_dir, "explain.json")
    resolved_calls_path = os.path.join(cache_dir, "resolved_calls.json")

    explain_db = _load_json(explain_path, {})
    if fqn not in explain_db:
        raise KeyError(f"Symbol not found in explain.json: {fqn}")

    item = explain_db[fqn]
    location = item.get("location", {})

    symbol_index = _build_symbol_index(repo_dir)
    symbol = _symbol_from_index(symbol_index, fqn)

    file_path = location.get("file") or (symbol.file_path if symbol else "")
    start_line = int(location.get("start_line") or (symbol.start_line if symbol else 1))
    end_line = int(location.get("end_line") or (symbol.end_line if symbol else start_line))
    if not file_path:
        raise FileNotFoundError(f"Missing location for symbol: {fqn}")

    extracted = _extract_signature_returns_docstring(item)
    snippet = _extract_snippet(file_path, start_line, end_line)

    callgraph = _build_callgraph(resolved_calls_path)
    callers = sorted({c.caller_fqn for c in callgraph.callers_of(fqn)})
    callees = sorted({c.callee_fqn for c in callgraph.callees_of(fqn) if c.callee_fqn})

    payload = {
        "fqn": fqn,
        "location": {
            "file": file_path,
            "start_line": start_line,
            "end_line": end_line,
        },
        "signature": extracted["signature"],
        "docstring": extracted["docstring"],
        "returns": extracted["returns"],
        "callers_1hop": callers,
        "callees_1hop": callees,
        "snippet": snippet,
    }
    return payload


def _llm_cache_path(repo_dir: str) -> str:
    return os.path.join(get_cache_dir(repo_dir), LLM_CACHE_FILE)


def _model_for_provider(provider: str) -> str:
    if provider == "gemini":
        return GEMINI_MODEL
    if provider == "groq":
        return GROQ_MODEL
    if provider == "xai":
        return os.getenv("CODEMAP_XAI_MODEL", XAI_DEFAULT_MODEL).strip() or XAI_DEFAULT_MODEL
    return ""


def _cache_key(provider: str, model: str, payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    material = f"{provider}|{model}|{serialized}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _build_prompt(payload: Dict[str, Any]) -> str:
    return (
        f"System instruction:\n{SYSTEM_INSTRUCTION}\n\n"
        "Use this code context JSON:\n"
        f"{json.dumps(payload, ensure_ascii=True)}"
    )


def _truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).strip()


def _strip_markdown(text: str) -> str:
    cleaned = text.replace("###", " ").replace("**", " ").replace("*", " ")
    cleaned = cleaned.replace("`", " ").replace("#", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_notes(raw: str) -> str:
    tokens = re.split(r"[.;]\s*", raw)
    picked: List[str] = []
    keywords = ("risk", "pitfall", "edge", "caution", "coupl", "brittle", "error")
    for t in tokens:
        low = t.lower()
        if any(k in low for k in keywords):
            frag = t.strip()
            if frag:
                picked.append(frag)
        if len(picked) >= 3:
            break
    return "; ".join(picked)


def _connections_line(context: Dict[str, Any]) -> str:
    callers = context.get("callers_1hop", [])[:2]
    callees = context.get("callees_1hop", [])[:3]
    if not callers and not callees:
        return "Connections: none"

    caller_part = ", ".join(callers) if callers else "none"
    callee_part = ", ".join(callees) if callees else "none"
    return f"Connections: called by {caller_part}; calls {callee_part}"


def _normalize_summary(raw_summary: str, context: Dict[str, Any]) -> str:
    raw = _strip_markdown(raw_summary or "")
    what_line = ""
    notes_line = ""

    for line in (raw_summary or "").splitlines():
        line_clean = _strip_markdown(line)
        line_clean = re.sub(r"^\s*\d+\)\s*", "", line_clean)
        lower = line_clean.lower()
        if lower.startswith("what it does:"):
            what_line = "What it does: " + line_clean.split(":", 1)[1].strip()
        elif lower.startswith("notes:"):
            notes_line = "Notes: " + line_clean.split(":", 1)[1].strip()

    if not what_line:
        sentence = re.split(r"(?<=[.!?])\s+", raw)[0].strip() if raw else ""
        sentence = re.sub(r"^\s*\d+\)\s*", "", sentence)
        sentence = re.sub(r"(?i)^what it does:\s*", "", sentence).strip()
        if not sentence:
            sentence = f"{context.get('fqn', 'Symbol')} performs its core behavior."
        what_line = f"What it does: {sentence}"

    conn_line = _connections_line(context)

    if not notes_line:
        notes = _extract_notes(raw)
        notes_line = f"Notes: {notes}" if notes else "Notes:"

    result = "\n".join([what_line, conn_line, notes_line])
    return _truncate_words(result, 90)


def _invoke_gemini(payload: Dict[str, Any]) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    prompt = _build_prompt(payload)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 200,
        },
    }
    req = request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text


def _invoke_groq(payload: Dict[str, Any]) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": _build_prompt(payload)},
        ],
        "temperature": 0.3,
        "max_tokens": 200,
    }
    req = request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("Groq returned no choices")
    content = choices[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Groq returned empty content")
    return content


def _invoke_xai(payload: Dict[str, Any]) -> str:
    api_key = os.getenv("XAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("XAI_API_KEY is not set")

    model = _model_for_provider("xai")
    endpoint = "https://api.x.ai/v1/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": _build_prompt(payload)},
        ],
        "temperature": 0.3,
        "max_tokens": 200,
    }
    req = request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("xAI returned no choices")
    content = choices[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("xAI returned empty content")
    return content


def _try_provider(provider: str, payload: Dict[str, Any]) -> str:
    if provider == "gemini":
        return _invoke_gemini(payload)
    if provider == "groq":
        return _invoke_groq(payload)
    if provider == "xai":
        return _invoke_xai(payload)
    raise RuntimeError(f"Unsupported provider: {provider}")


def llm_explain_symbol(fqn: str, repo_dir: str, no_cache: bool = False) -> Dict[str, Any]:
    repo_dir = os.path.abspath(repo_dir)
    env_no_cache = os.getenv("CODEMAP_NO_CACHE", "").strip() == "1"
    skip_cache = no_cache or env_no_cache

    try:
        context = build_symbol_context(fqn=fqn, repo_dir=repo_dir)
    except Exception as e:
        return {"ok": False, "summary": "", "provider": "", "model": "", "cached": False, "error": str(e)}

    redacted_context = _redact_payload(context)
    cache_path = _llm_cache_path(repo_dir)
    cache = _load_json(cache_path, {})

    requested_provider = os.getenv("CODEMAP_LLM", "").strip().lower()
    allow_fallback = os.getenv("CODEMAP_ALLOW_FALLBACK", "").strip() == "1"
    default_order = ["gemini"]
    if os.getenv("XAI_API_KEY", "").strip():
        default_order.append("xai")
    default_order.append("groq")

    if requested_provider in {"gemini", "groq", "xai"}:
        providers = [requested_provider]
        if allow_fallback:
            providers.extend([p for p in default_order if p != requested_provider])
    elif requested_provider:
        return {
            "ok": False,
            "summary": "",
            "provider": requested_provider,
            "model": "",
            "cached": False,
            "error": "CODEMAP_LLM must be 'gemini', 'groq', or 'xai'",
        }
    else:
        providers = default_order

    if not skip_cache:
        for provider in providers:
            model = _model_for_provider(provider)
            key = _cache_key(provider, model, redacted_context)
            if key in cache:
                cached_summary = _normalize_summary(cache[key].get("summary", ""), redacted_context)
                return {
                    "ok": True,
                    "summary": cached_summary,
                    "provider": cache[key].get("provider", provider),
                    "model": cache[key].get("model", model),
                    "cached": True,
                    "error": None,
                }

    errors: List[str] = []
    last_provider = ""
    last_model = ""
    for provider in providers:
        last_provider = provider
        last_model = _model_for_provider(provider)
        try:
            raw_summary = _try_provider(provider, redacted_context)
            summary = _normalize_summary(raw_summary, redacted_context)
            key = _cache_key(provider, last_model, redacted_context)
            cache[key] = {
                "provider": provider,
                "model": last_model,
                "summary": summary,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            _save_json(cache_path, cache)
            return {
                "ok": True,
                "summary": summary,
                "provider": provider,
                "model": last_model,
                "cached": False,
                "error": None,
            }
        except error.HTTPError as e:
            errors.append(f"{provider} HTTP {e.code} {e.reason}")
        except Exception as e:
            errors.append(f"{provider} error: {str(e)}")

    return {
        "ok": False,
        "summary": "",
        "provider": last_provider,
        "model": last_model,
        "cached": False,
        "error": "; ".join(errors) if errors else "LLM invocation failed",
    }
