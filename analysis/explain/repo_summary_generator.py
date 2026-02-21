from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib import error, request


PROMPT_TEMPLATE_VERSION = "repo_summary_v1"
MAX_CONTEXT_BYTES = 4096


def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _count_tree_files(node: Dict[str, Any]) -> int:
    if not isinstance(node, dict):
        return 0
    if node.get("type") == "file":
        return 1
    total = 0
    for child in node.get("children", []):
        total += _count_tree_files(child)
    return total


def _short_file(path: str) -> str:
    return os.path.basename((path or "").replace("\\", "/"))


def _mk_symbol_entry(fqn: str, symbols: Dict[str, Any]) -> Dict[str, Any]:
    s = symbols.get(fqn, {})
    loc = s.get("location", {}) if isinstance(s, dict) else {}
    return {
        "fqn": fqn,
        "in": int(s.get("fan_in", 0)) if isinstance(s, dict) else 0,
        "out": int(s.get("fan_out", 0)) if isinstance(s, dict) else 0,
        "file": _short_file(loc.get("file", "")),
        "line": int(loc.get("start_line", -1)),
    }


def _json_size_bytes(obj: Any) -> int:
    return len(json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8"))


def build_repo_summary_context(repo_cache_dir: str) -> dict:
    arch_path = os.path.join(repo_cache_dir, "architecture_metrics.json")
    dep_path = os.path.join(repo_cache_dir, "dependency_cycles.json")
    analysis_path = os.path.join(repo_cache_dir, "analysis_metrics.json")
    tree_path = os.path.join(repo_cache_dir, "project_tree.json")

    if not os.path.exists(arch_path):
        raise FileNotFoundError(f"Missing {arch_path}")
    if not os.path.exists(dep_path):
        raise FileNotFoundError(f"Missing {dep_path}")

    arch = _load_json(arch_path, {})
    dep = _load_json(dep_path, {})
    analysis = _load_json(analysis_path, {})
    tree = _load_json(tree_path, {})

    repo_prefix = str(arch.get("repo_prefix", "") or "")
    repo_info = arch.get("repo", {}) if isinstance(arch, dict) else {}
    symbols = arch.get("symbols", {}) if isinstance(arch, dict) else {}

    orchestrators_src = repo_info.get("orchestrators", []) or []
    if orchestrators_src and isinstance(orchestrators_src[0], dict):
        orchestrators_fqns = [x.get("fqn", "") for x in orchestrators_src]
    else:
        orchestrators_fqns = [str(x) for x in orchestrators_src]
    if not orchestrators_fqns:
        top = repo_info.get("top_fan_out", []) or []
        orchestrators_fqns = [x.get("fqn", "") for x in top if isinstance(x, dict)]

    critical_src = repo_info.get("critical_symbols", []) or []
    if critical_src and isinstance(critical_src[0], dict):
        critical_fqns = [x.get("fqn", "") for x in critical_src]
    else:
        critical_fqns = [str(x) for x in critical_src]
    if not critical_fqns:
        top = repo_info.get("top_fan_in", []) or []
        critical_fqns = [x.get("fqn", "") for x in top if isinstance(x, dict)]

    dead_fqns = [str(x) for x in (repo_info.get("dead_symbols", []) or [])]
    cycles = dep.get("cycles", []) or []

    orchestrators = [_mk_symbol_entry(fqn, symbols) for fqn in orchestrators_fqns if fqn][:5]
    critical_apis = [_mk_symbol_entry(fqn, symbols) for fqn in critical_fqns if fqn][:5]
    dead_symbols = [_mk_symbol_entry(fqn, symbols) for fqn in dead_fqns if fqn][:5]
    cycle_preview = [c for c in cycles if isinstance(c, list)][:5]

    calls_total = int((analysis.get("stats", {}) or {}).get("total_calls", 0))
    unresolved_calls = int((analysis.get("stats", {}) or {}).get("unresolved_calls", 0))
    files_count = _count_tree_files(tree) if isinstance(tree, dict) else 0

    context = {
        "repo_prefix": repo_prefix,
        "counts": {
            "symbols": int(repo_info.get("total_nodes", len(symbols))),
            "calls": calls_total,
            "files": files_count,
            "unresolved_calls": unresolved_calls,
            "cycles": int(dep.get("cycle_count", len(cycle_preview))),
        },
        "orchestrators": orchestrators,
        "critical_apis": critical_apis,
        "dead_symbols": dead_symbols,
        "dependency_cycles": [{"cycle": c, "kind": "module"} for c in cycle_preview],
    }

    # Keep payload compact: trim progressively if required.
    if _json_size_bytes(context) > MAX_CONTEXT_BYTES:
        context["dependency_cycles"] = context["dependency_cycles"][:3]
    if _json_size_bytes(context) > MAX_CONTEXT_BYTES:
        context["dead_symbols"] = context["dead_symbols"][:3]
    if _json_size_bytes(context) > MAX_CONTEXT_BYTES:
        context["orchestrators"] = context["orchestrators"][:3]
        context["critical_apis"] = context["critical_apis"][:3]

    return context


def _provider_order_from_env(llm_client) -> Tuple[List[str], str]:
    requested = os.getenv("CODEMAP_LLM", "").strip().lower()
    allow_fallback = os.getenv("CODEMAP_ALLOW_FALLBACK", "").strip() == "1"

    default = ["gemini"]
    if os.getenv("XAI_API_KEY", "").strip():
        default.append("xai")
    default.append("groq")

    if requested in {"gemini", "groq", "xai"}:
        order = [requested]
        if allow_fallback:
            order.extend([p for p in default if p != requested])
        return order, ""
    if requested:
        return [], "CODEMAP_LLM must be 'gemini', 'groq', or 'xai'"
    return default, ""


def _provider_has_key(provider: str) -> bool:
    if provider == "gemini":
        return bool(os.getenv("GEMINI_API_KEY", "").strip())
    if provider == "groq":
        return bool(os.getenv("GROQ_API_KEY", "").strip())
    if provider == "xai":
        return bool(os.getenv("XAI_API_KEY", "").strip())
    return False


def _model_for_provider(llm_client, provider: str) -> str:
    if provider == "gemini":
        return getattr(llm_client, "GEMINI_MODEL", "gemini-2.5-flash-lite")
    if provider == "groq":
        return getattr(llm_client, "GROQ_MODEL", "llama-3.1-8b-instant")
    if provider == "xai":
        default_model = getattr(llm_client, "XAI_DEFAULT_MODEL", "grok-code-fast-1")
        return os.getenv("CODEMAP_XAI_MODEL", default_model).strip() or default_model
    return ""


def _repo_prompt(context: Dict[str, Any]) -> str:
    return (
        "Return ONLY JSON with keys: one_liner, bullets, notes.\n"
        "Constraints:\n"
        "- one_liner: one sentence, <= 120 chars\n"
        "- bullets: 3-7 concise bullets (no markdown markers)\n"
        "- notes: 0-5 concise warnings/risks\n"
        "- simple developer language\n"
        "- mention whether codebase is script-style/module-level or library-style\n"
        "- mention major orchestration entrypoints and hotspots/cycles\n\n"
        f"Context JSON:\n{json.dumps(context, ensure_ascii=True)}"
    )


def _invoke_gemini(prompt: str, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.25, "maxOutputTokens": 260},
    }
    req = request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    cands = data.get("candidates", [])
    if not cands:
        raise RuntimeError("Gemini returned no candidates")
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text


def _invoke_openai_compatible(endpoint: str, api_key: str, model: str, prompt: str) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise software architecture assistant. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.25,
        "max_tokens": 260,
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
        raise RuntimeError("LLM returned no choices")
    text = choices[0].get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("LLM returned empty content")
    return text


def _invoke_provider(provider: str, model: str, prompt: str) -> str:
    if provider == "gemini":
        return _invoke_gemini(prompt, model)
    if provider == "groq":
        return _invoke_openai_compatible(
            endpoint="https://api.groq.com/openai/v1/chat/completions",
            api_key=os.getenv("GROQ_API_KEY", "").strip(),
            model=model,
            prompt=prompt,
        )
    if provider == "xai":
        return _invoke_openai_compatible(
            endpoint="https://api.x.ai/v1/chat/completions",
            api_key=os.getenv("XAI_API_KEY", "").strip(),
            model=model,
            prompt=prompt,
        )
    raise RuntimeError(f"Unsupported provider: {provider}")


def _extract_json_obj(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _clean_line(text: str, max_len: int) -> str:
    cleaned = re.sub(r"[#*`]+", " ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len]


def _normalize_llm_summary(obj: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    one_liner = _clean_line(obj.get("one_liner", ""), 140)
    bullets = obj.get("bullets", [])
    notes = obj.get("notes", [])

    if not isinstance(bullets, list):
        bullets = []
    if not isinstance(notes, list):
        notes = []

    bullets_clean = [_clean_line(x, 120) for x in bullets if _clean_line(x, 120)]
    notes_clean = [_clean_line(x, 120) for x in notes if _clean_line(x, 120)]
    bullets_clean = bullets_clean[:7]
    notes_clean = notes_clean[:5]

    # Fallback deterministic text if model did not comply.
    if not one_liner:
        style = "module-level script" if any(o.get("fqn", "").endswith(".<module>") for o in context.get("orchestrators", [])) else "library-style codebase"
        one_liner = f"{context.get('repo_prefix', 'Repo')} is a {style} with static-callgraph hotspots."

    if len(bullets_clean) < 3:
        c = context.get("counts", {})
        bullets_seed = [
            f"Symbols: {c.get('symbols', 0)}, calls: {c.get('calls', 0)}, files: {c.get('files', 0)}.",
            f"Orchestrators: {len(context.get('orchestrators', []))}, critical APIs: {len(context.get('critical_apis', []))}.",
            f"Dependency cycles: {c.get('cycles', 0)}, unresolved calls: {c.get('unresolved_calls', 0)}.",
        ]
        for b in bullets_seed:
            if len(bullets_clean) >= 3:
                break
            bullets_clean.append(_clean_line(b, 120))

    return {
        "one_liner": one_liner,
        "bullets": bullets_clean[:7],
        "notes": notes_clean[:5],
    }


def generate_repo_summary(repo_cache_dir: str, llm_client) -> dict:
    repo_cache_dir = os.path.abspath(repo_cache_dir)
    llm_cache_path = os.path.join(repo_cache_dir, "llm_cache.json")
    context = build_repo_summary_context(repo_cache_dir)

    redactor = getattr(llm_client, "_redact_payload", None)
    if callable(redactor):
        context = redactor(context)

    canonical = json.dumps(
        {"v": PROMPT_TEMPLATE_VERSION, "context": context},
        sort_keys=True,
        ensure_ascii=True,
    )
    ctx_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    cache_key = f"repo_summary:{ctx_hash}"
    llm_cache = _load_json(llm_cache_path, {})

    cached_entry = llm_cache.get(cache_key)
    if isinstance(cached_entry, dict):
        return {
            "ok": True,
            "cached": True,
            "provider": cached_entry.get("provider"),
            "model": cached_entry.get("model"),
            "summary": cached_entry.get("summary", {}),
            "error": None,
        }

    providers, order_error = _provider_order_from_env(llm_client)
    if order_error:
        return {"ok": False, "cached": False, "provider": None, "model": None, "summary": {}, "error": order_error}

    prompt = _repo_prompt(context)
    errors: List[str] = []
    for provider in providers:
        model = _model_for_provider(llm_client, provider)
        if not _provider_has_key(provider):
            errors.append(f"{provider}: missing API key")
            continue

        try:
            raw = _invoke_provider(provider, model, prompt)
            parsed = _extract_json_obj(raw)
            normalized = _normalize_llm_summary(parsed, context)
            summary = {
                **normalized,
                "top_orchestrators": context.get("orchestrators", []),
                "critical_apis": context.get("critical_apis", []),
                "dependency_cycles": context.get("dependency_cycles", []),
            }

            llm_cache[cache_key] = {
                "provider": provider,
                "model": model,
                "summary": summary,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            _save_json(llm_cache_path, llm_cache)
            return {
                "ok": True,
                "cached": False,
                "provider": provider,
                "model": model,
                "summary": summary,
                "error": None,
            }
        except error.HTTPError as e:
            errors.append(f"{provider}: HTTP {e.code} {e.reason}")
        except Exception as e:
            errors.append(f"{provider}: {str(e)}")

    return {
        "ok": False,
        "cached": False,
        "provider": None,
        "model": None,
        "summary": {},
        "error": "; ".join(errors) if errors else "No LLM provider available",
    }
