#!/usr/bin/env python3
"""Build a clean, portable release ZIP of the AEGIS_Middleware project.

The archive contains exactly what another developer needs to extract, read,
install and run the project: all source, tests, docs, configuration, Docker
files and dependency manifests (including lockfiles).

It deliberately omits anything that is reinstallable, regenerable,
machine-specific or secret. Nothing is deleted from the working tree: files
are copied into a throwaway staging directory, which is archived and removed.

Usage:
    python scripts/make_release_zip.py [--out DIR] [--name NAME] [--keep-staging]

By default the ZIP is written to the repository's PARENT directory, so the
archive is never nested inside the tree it archives.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Exclusion list. Each entry is matched against the repo-relative POSIX path
# of a candidate file and against its basename.
# ---------------------------------------------------------------------------

#: Directory names dropped wherever they appear in the tree.
EXCLUDE_DIRS = (
    ".git",                 # version-control history: rebuildable from the remote
    "__pycache__",          # compiled Python bytecode
    ".pytest_cache",        # pytest run cache
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",         # npm dependencies: restored by `npm install`
    ".venv", "venv", "env", # Python virtualenvs: restored by `pip install -r`
    ".next", "out", "build", "dist",  # frontend / python build output
    "htmlcov",              # coverage HTML report
    ".hf_cache",            # HuggingFace download cache
    ".ipynb_checkpoints",
    ".vscode", ".idea",     # editor settings
    ".kilo",                # local agent/tool settings, machine-specific
    ".claude",
    "neo4j_data", "neo4j_logs",  # Neo4j container volumes
)

#: Glob patterns dropped wherever they match.
EXCLUDE_GLOBS = (
    # Compiled / cached Python
    "*.pyc", "*.pyo", "*.pyd", "*$py.class", "*.so",
    # Local databases holding development data
    "*.db", "*.sqlite", "*.sqlite3", "*.db-journal", "*.db-wal", "*.db-shm",
    # Logs, temp files, editor swap files
    "*.log", "*.tmp", "*.bak", "*.orig", "*.rej", "*.swp", "*.swo", "*~",
    # Coverage artifacts
    ".coverage", ".coverage.*", "coverage.xml", "coverage-final.json",
    # Model weights / caches that are downloaded on demand
    "*.bin", "*.safetensors", "*.onnx", "*.pt", "*.pth", "*.h5", "*.ckpt",
    "*.gguf", "*.tflite", "*.msgpack", "*.joblib", "*.pkl",
    # OS cruft
    ".DS_Store", "._*", "Thumbs.db", "desktop.ini",
    # Archives: never nest a build of the project inside itself
    "*.zip", "*.tar", "*.tar.gz", "*.tgz", "*.7z", "*.rar",
    # Rendered video and audio. No source file in this repo is one of these,
    # and everything under submission-video/ is regenerable from the
    # committed HTML and build scripts. Keeps --all-files from sweeping in
    # tens of MB of clips, scratch narration and intermediate renders.
    "*.mp4", "*.mkv", "*.mov", "*.webm", "*.avi",
    "*.wav", "*.mp3", "*.aac", "*.m4a", "*.flac", "*.ogg",
    "submission-video/video-assets/clips/*",
    "submission-video/video-assets/build/*",
    "submission-video/video-assets/raw/*",
    "submission-video/video-assets/narration/wav/*",
    "submission-video/video-assets/narration/final/*",
    # Secrets. .env.example is re-admitted by ALWAYS_INCLUDE below.
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks",
    "*.keystore", "*.crt", "*.cer", "id_rsa*", "id_ed25519*",
    "credentials", "credentials.*", "*secret*", "*.secrets",
)

#: Patterns that override EXCLUDE_GLOBS. Safe, committed templates and docs
#: only. Checked AFTER the EXCLUDE_DIRS pass, so a README inside
#: node_modules/ or .git/ is still dropped; this only rescues files whose
#: *name or path pattern* would otherwise match EXCLUDE_GLOBS -- for example
#: the README explaining what belongs in an otherwise-excluded output folder.
ALWAYS_INCLUDE = (
    ".env.example",
    ".env.sample",
    ".env.template",
    "README.md",
)

#: Repo-relative paths added even when git does not track them yet, so the
#: recipient of the archive can rebuild it. Missing paths are skipped.
EXTRA_PATHS = (
    "scripts/make_release_zip.py",
)


def _matches(path, patterns):
    """Return the first pattern in *patterns* matching the path or its basename."""
    base = path.rsplit("/", 1)[-1]
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(base, pattern):
            return pattern
    return None


def classify(rel_path):
    """Return the reason *rel_path* is excluded, or None to include it."""
    parts = rel_path.split("/")

    # Directory components only, never the final filename.
    for name in parts[:-1]:
        if name in EXCLUDE_DIRS:
            return "directory '%s'" % name

    if _matches(rel_path, ALWAYS_INCLUDE):
        return None

    hit = _matches(rel_path, EXCLUDE_GLOBS)
    if hit:
        return "pattern '%s'" % hit

    return None


def git_tracked_files(repo):
    """Repo-relative paths of files tracked by git, or None outside a repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--exclude-standard"],
            cwd=str(repo), capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in result.stdout.split("\0") if p]


def walk_files(repo):
    """Every file under *repo*, repo-relative, pruning excluded directories."""
    found = []
    for dirpath, dirnames, filenames in os.walk(str(repo)):
        rel_dir = Path(dirpath).relative_to(repo).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            found.append(prefix + name)
    return found


def main():
    repo = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None,
                        help="directory for the ZIP (default: the repo's parent)")
    parser.add_argument("--name", default="AEGIS_Middleware",
                        help="archive and extracted-root name")
    parser.add_argument("--all-files", action="store_true",
                        help="walk the filesystem instead of using 'git ls-files'")
    parser.add_argument("--keep-staging", action="store_true",
                        help="leave the staging directory in place for inspection")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve() if args.out else repo.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / (args.name + ".zip")

    candidates = None if args.all_files else git_tracked_files(repo)
    if candidates is None:
        source = "filesystem walk"
        candidates = walk_files(repo)
    else:
        source = "git ls-files"

    for extra in EXTRA_PATHS:
        if extra not in candidates and (repo / extra).is_file():
            candidates.append(extra)

    included = []
    excluded = []
    for rel in sorted(candidates):
        if not (repo / rel).is_file():
            continue                            # submodule or stale index entry
        reason = classify(rel)
        if reason:
            excluded.append((rel, reason))
        else:
            included.append(rel)

    staging_parent = Path(tempfile.mkdtemp(prefix="aegis-release-"))
    staging_root = staging_parent / args.name
    try:
        for rel in included:
            target = staging_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(repo / rel), str(target))

        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel in included:
                zf.write(str(staging_root / rel), args.name + "/" + rel)
    finally:
        if args.keep_staging:
            print("staging kept at: %s" % staging_root)
        else:
            shutil.rmtree(str(staging_parent), ignore_errors=True)

    size = zip_path.stat().st_size
    print("candidate source : %s (%d entries)" % (source, len(candidates)))
    print("files included   : %d" % len(included))
    print("files excluded   : %d" % len(excluded))
    for rel, reason in excluded:
        print("  - %s  [%s]" % (rel, reason))
    print("archive          : %s" % zip_path)
    print("archive size     : %.2f MB (%d bytes)" % (size / 1048576.0, size))

    if size >= 50 * 1024 * 1024:
        print("ERROR: archive is 50 MB or larger.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
