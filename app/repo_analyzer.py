# app/repo_analyzer.py
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from app.config import settings


@dataclass
class Hit:
    # One search match: file + line number + line text
    path: str
    line_no: int
    line: str


def _normalize_path(p: str) -> str:
    # Make Windows paths consistent
    return p.replace("\\", "/")


def _safe_read_lines(full_path: str) -> List[str]:
    # Read file lines safely (replace bad chars)
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except Exception:
        return []


def _extract_snippet(lines: List[str], center_line_1based: int, radius: int = 8) -> str:
    # Extract +/- radius lines around the hit line
    if not lines:
        return ""
    center_idx = max(0, center_line_1based - 1)
    start = max(0, center_idx - radius)
    end = min(len(lines), center_idx + radius + 1)

    out = []
    for i in range(start, end):
        out.append(f"{i+1:>4}: {lines[i].rstrip()}")
    return "\n".join(out)


def _infer_java_class_name(lines: List[str]) -> Optional[str]:
    # Extract class/interface/enum name
    rx = re.compile(r"^\s*(public\s+)?(final\s+)?(class|interface|enum)\s+([A-Za-z0-9_]+)\b")
    for line in lines[:200]:
        m = rx.match(line)
        if m:
            return m.group(4)
    return None


def _infer_java_package(lines: List[str]) -> Optional[str]:
    # Extract "package com.foo.bar;"
    rx = re.compile(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;")
    for line in lines[:80]:
        m = rx.match(line)
        if m:
            return m.group(1)
    return None


def _infer_role(lines: List[str]) -> Optional[str]:
    # Quick stereotype detection
    text = "\n".join(lines[:250])
    if "@RestController" in text or "@Controller" in text:
        return "controller"
    if "@Service" in text:
        return "service"
    if "@Repository" in text:
        return "repository"
    if "@Entity" in text:
        return "entity"
    return None


def _keywordize(title: str, description: str, max_keywords: int = 12) -> List[str]:
    # Deterministic keyword extraction (no AI here)
    raw = f"{title}\n{description}".lower()
    raw = re.sub(r"[^a-z0-9\s\-_/]", " ", raw)
    tokens = [t for t in raw.split() if len(t) >= 3]

    stop = {
        "the", "and", "for", "with", "from", "this", "that", "then", "when",
        "into", "your", "need", "must", "should", "will", "add", "create",
        "update", "fix", "api", "service", "spring", "boot",
    }

    dedup = []
    seen = set()
    for t in tokens:
        if t in stop:
            continue
        if t in seen:
            continue
        seen.add(t)
        dedup.append(t)

    return dedup[:max_keywords]


def _have_rg() -> bool:
    # Check if ripgrep exists
    try:
        subprocess.run(["rg", "--version"], capture_output=True, text=True, check=False)
        return True
    except Exception:
        return False


def _run_rg(repo_path: str, kw: str, max_hits: int = 40) -> List[Hit]:
    # Run: rg --line-number --fixed-strings kw repo_path
    cmd = ["rg", "--line-number", "--no-heading", "--fixed-strings", kw, repo_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    # returncode: 0=matches, 1=no matches, other=error
    if proc.returncode not in (0, 1):
        return []

    hits: List[Hit] = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        path, line_no_str, content = parts
        if not line_no_str.isdigit():
            continue

        hits.append(Hit(
            path=_normalize_path(os.path.relpath(path, repo_path)),
            line_no=int(line_no_str),
            line=content.strip(),
        ))
        if len(hits) >= max_hits:
            break

    return hits


def _run_git_grep(repo_path: str, kw: str, max_hits: int = 40) -> List[Hit]:
    # Fallback: git -C repo_path grep -n --fixed-strings kw
    cmd = ["git", "-C", repo_path, "grep", "-n", "--fixed-strings", kw]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if proc.returncode not in (0, 1):
        return []

    hits: List[Hit] = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        path, line_no_str, content = parts
        if not line_no_str.isdigit():
            continue

        hits.append(Hit(
            path=_normalize_path(path),
            line_no=int(line_no_str),
            line=content.strip(),
        ))
        if len(hits) >= max_hits:
            break

    return hits


def _find_tests(repo_path: str, package_hint: Optional[str], class_name: Optional[str]) -> List[str]:
    # Find likely tests in src/test/java
    test_root = os.path.join(repo_path, "src", "test")
    if not os.path.isdir(test_root):
        return []

    candidates: List[str] = []
    for root, _, files in os.walk(test_root):
        for fn in files:
            if not fn.endswith(".java"):
                continue
            if not (fn.endswith("Test.java") or fn.endswith("IT.java")):
                continue
            full = os.path.join(root, fn)
            candidates.append(_normalize_path(os.path.relpath(full, repo_path)))

    # Rank candidates by whether they mention the class/package
    ranked = []
    for p in candidates:
        lines = _safe_read_lines(os.path.join(repo_path, p))
        head = "\n".join(lines[:500])
        score = 0
        if class_name and class_name in head:
            score += 3
        if package_hint and package_hint in head:
            score += 1
        if score > 0:
            ranked.append((score, p))

    ranked.sort(key=lambda x: x[0], reverse=True)
    if ranked:
        return [p for _, p in ranked[:8]]

    # Fallback: tests near the same package path
    if package_hint:
        pkg_path = package_hint.replace(".", "/")
        near = [p for p in candidates if pkg_path in p]
        return near[:8]

    return candidates[:5]


async def analyze_repo_for_ticket(title: str, description: str) -> Dict[str, Any]:
    """
    Repo Analysis Agent:
    Output is a JSON-like dict used as evidence inside DEV_GUIDE.
    """
    repo_path = settings.local_repo_path
    if not repo_path:
        return {"error": "LOCAL_REPO_PATH is not set", "keywords_used": [], "impacted_files": [], "impacted_modules": [], "test_targets": []}

    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        return {"error": f"LOCAL_REPO_PATH not found: {repo_path}", "keywords_used": [], "impacted_files": [], "impacted_modules": [], "test_targets": []}

    keywords = _keywordize(title, description)
    use_rg = _have_rg()

    all_hits: List[Hit] = []
    for kw in keywords:
        all_hits.extend(_run_rg(repo_path, kw) if use_rg else _run_git_grep(repo_path, kw))

    # Group hits by Java file
    hits_by_file: Dict[str, List[Hit]] = {}
    for h in all_hits:
        if not h.path.endswith(".java"):
            continue
        hits_by_file.setdefault(h.path, []).append(h)

    impacted_files: List[Dict[str, Any]] = []
    for path, hits in hits_by_file.items():
        full_path = os.path.join(repo_path, path)
        lines = _safe_read_lines(full_path)

        class_name = _infer_java_class_name(lines)
        pkg = _infer_java_package(lines)
        role = _infer_role(lines)

        hits_sorted = sorted(hits, key=lambda x: x.line_no)

        snippets = []
        for hh in hits_sorted[:2]:
            snippets.append(_extract_snippet(lines, hh.line_no, radius=8))

        impacted_files.append({
            "path": path,
            "class_name": class_name,
            "package": pkg,
            "role": role,
            "hit_count": len(hits),
            "sample_hits": [{"line_no": x.line_no, "line": x.line} for x in hits_sorted[:5]],
            "snippets": snippets,
            "score": len(hits),
        })

    # Rank most relevant first
    impacted_files.sort(key=lambda x: x["score"], reverse=True)

    # Infer “module” by top-level directory (works for multi-module repos)
    module_scores: Dict[str, int] = {}
    for f in impacted_files[:30]:
        parts = f["path"].split("/")
        if len(parts) >= 2:
            module_scores[parts[0]] = module_scores.get(parts[0], 0) + f["hit_count"]

    impacted_modules = [{"name": m, "score": sc, "reason": "keyword hits"} for m, sc in sorted(module_scores.items(), key=lambda x: x[1], reverse=True)]

    test_targets: List[str] = []
    if impacted_files:
        top = impacted_files[0]
        test_targets = _find_tests(repo_path, top.get("package"), top.get("class_name"))

    return {
        "error": None,
        "keywords_used": keywords,
        "search_tool": "ripgrep" if use_rg else "git_grep",
        "impacted_modules": impacted_modules[:8],
        "impacted_files": impacted_files[:12],
        "test_targets": test_targets,
    }
