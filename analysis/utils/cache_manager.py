import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".codemap_cache",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
}


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _manifest_path(path: str) -> str:
    return os.path.join(get_cache_dir(path), "manifest.json")


def compute_repo_hash(path: str) -> str:
    repo_path = os.path.abspath(path)
    digest = hashlib.sha256(repo_path.encode("utf-8")).hexdigest()
    return digest[:16]


def get_cache_dir(path: str) -> str:
    return os.path.join(_project_root(), ".codemap_cache", compute_repo_hash(path))


def collect_fingerprints(path: str) -> Dict[str, Dict[str, int]]:
    repo_path = os.path.abspath(path)
    fingerprints: Dict[str, Dict[str, int]] = {}

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            file_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(file_path, repo_path).replace(os.sep, "/")
            stat = os.stat(file_path)
            fingerprints[rel_path] = {
                "mtime_ns": int(stat.st_mtime_ns),
                "size": int(stat.st_size),
            }

    return dict(sorted(fingerprints.items(), key=lambda x: x[0]))


def diff_fingerprints(
    old: Dict[str, Dict[str, int]],
    new: Dict[str, Dict[str, int]],
) -> Dict[str, Any]:
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    modified = sorted(
        key for key in (old_keys & new_keys)
        if old.get(key) != new.get(key)
    )

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "changed_files": len(added) + len(removed) + len(modified),
    }


def load_manifest(path: str) -> Dict[str, Any]:
    manifest_path = _manifest_path(path)
    if not os.path.exists(manifest_path):
        return {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(path: str, manifest: Dict[str, Any]) -> str:
    cache_dir = get_cache_dir(path)
    os.makedirs(cache_dir, exist_ok=True)
    manifest_path = _manifest_path(path)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest_path


def should_rebuild(path: str) -> bool:
    manifest = load_manifest(path)
    if not manifest:
        return True

    old_fingerprints = manifest.get("fingerprints", {})
    new_fingerprints = collect_fingerprints(path)
    delta = diff_fingerprints(old_fingerprints, new_fingerprints)
    if delta["changed_files"] > 0:
        return True

    cache_dir = get_cache_dir(path)
    resolved_calls_path = os.path.join(cache_dir, "resolved_calls.json")
    explain_path = os.path.join(cache_dir, "explain.json")
    return not (os.path.exists(resolved_calls_path) and os.path.exists(explain_path))


def build_manifest(
    path: str,
    fingerprints: Dict[str, Dict[str, int]],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    repo_path = os.path.abspath(path)
    cache_dir = get_cache_dir(path)
    manifest = {
        "repo_path": repo_path,
        "repo_hash": compute_repo_hash(path),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "fingerprints": fingerprints,
        "paths": {
            "resolved_calls_path": os.path.join(cache_dir, "resolved_calls.json"),
            "explain_path": os.path.join(cache_dir, "explain.json"),
            "analysis_metrics_path": os.path.join(cache_dir, "analysis_metrics.json"),
            "llm_cache_path": os.path.join(cache_dir, "llm_cache.json"),
        },
    }
    if metadata:
        manifest.update(metadata)
    return manifest
