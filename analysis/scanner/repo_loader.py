# # Repository loader module
import os
from scanner.ignore_rules import IGNORE_DIRS, IGNORE_FILES

def load_repository(root_path, stats=None):
    if stats is None:
        stats = {
            "total_files": 0,
            "extensions": {}
        }

    tree = {}

    for item in os.listdir(root_path):
        if item in IGNORE_DIRS or item in IGNORE_FILES:
            continue

        full_path = os.path.join(root_path, item)

        if os.path.isdir(full_path):
            tree[item] = load_repository(full_path, stats)
        else:
            tree[item] = "FILE"
            stats["total_files"] += 1

            ext = os.path.splitext(item)[1]
            if ext:
                stats["extensions"][ext] = stats["extensions"].get(ext, 0) + 1

    return tree
