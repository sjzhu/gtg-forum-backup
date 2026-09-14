#!/usr/bin/env python3
"""Regenerate the pages-mode site from the current raw category data and push it
to the `pages` branch on origin, which GitHub Pages serves from.

This only republishes whatever is currently on disk in the six category
folders — it does not pull new data from the forum itself (that's
update_backup.py, run separately beforehand if you want fresh content first).

Usage: python3 tools/publish_pages.py [--no-push]
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the `public` repo
BUILD_DIR = ROOT.parent / "_pages_build"
BRANCH = "pages"
INDEX_FILE = "/tmp/gtg_pages_publish_index"
CUSTOM_DOMAIN = "gtg-forum-backup.thewyrmsuperior.com"

COMMIT_MESSAGE = (
    "Publish readable site (auto-generated, images served from main branch)\n\n"
    "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
    "Claude-Session: https://claude.ai/code/session_01CnVPEdNc5XKd9T1csJS6fX"
)


def git(args, env=None, capture=False):
    return subprocess.run(
        ["git"] + args, cwd=str(ROOT), env=env, check=True, text=True,
        capture_output=capture,
    )


def rev_parse_or_none(ref):
    try:
        return git(["rev-parse", ref], capture=True).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-push", action="store_true", help="Build the branch locally but don't push to origin")
    args = ap.parse_args()

    print("Regenerating pages-mode site...")
    gen_cmd = [sys.executable, str(ROOT / "tools" / "generate_readable_site.py"),
               "--mode", "pages", "--out", str(BUILD_DIR)]
    if CUSTOM_DOMAIN:
        gen_cmd += ["--cname", CUSTOM_DOMAIN]
    subprocess.run(gen_cmd, cwd=str(ROOT), check=True)

    plumbing_env = os.environ.copy()
    plumbing_env.update({
        "GIT_DIR": str(ROOT / ".git"),
        "GIT_WORK_TREE": str(BUILD_DIR),
        "GIT_INDEX_FILE": INDEX_FILE,
    })
    Path(INDEX_FILE).unlink(missing_ok=True)

    try:
        git(["add", "-A"], env=plumbing_env)
        tree = git(["write-tree"], env=plumbing_env, capture=True).stdout.strip()

        parent = rev_parse_or_none(f"refs/heads/{BRANCH}")
        if parent:
            parent_tree = git(["rev-parse", f"{parent}^{{tree}}"], capture=True).stdout.strip()
            if parent_tree == tree:
                print("No changes since the last publish; nothing to do.")
                return

        commit_args = ["commit-tree", tree, "-m", COMMIT_MESSAGE]
        if parent:
            commit_args += ["-p", parent]
        commit = git(commit_args, env=plumbing_env, capture=True).stdout.strip()
        git(["update-ref", f"refs/heads/{BRANCH}", commit])
    finally:
        Path(INDEX_FILE).unlink(missing_ok=True)

    print(f"Updated local {BRANCH} branch -> {commit}")

    if args.no_push:
        print(f"--no-push set; not pushing. Run `git push origin {BRANCH}` when ready.")
        return

    print(f"Pushing to origin/{BRANCH}...")
    git(["push", "origin", BRANCH])
    print("Done. GitHub Pages will rebuild automatically (usually under a minute).")


if __name__ == "__main__":
    main()
