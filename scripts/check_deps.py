#!/usr/bin/env python3
"""Check installed package versions and suggest updates."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _parse_pyproject(path: Path) -> list[dict[str, Any]]:
    try:
        import tomllib
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        try:
            import tomli
            data = tomli.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Error: cannot parse pyproject.toml: {exc}", file=sys.stderr)
            sys.exit(1)

    raw_deps: list[str] = data.get("project", {}).get("dependencies", [])
    result: list[dict[str, Any]] = []
    if isinstance(raw_deps, list):
        for dep in raw_deps:
            dep = dep.strip()
            if not dep:
                continue
            m = re.match(r"^([a-zA-Z0-9_.-]+)\s*((?:[><=~!]+\s*[\d.*]+(?:\s*,\s*[><=~!]+\s*[\d.*]+)*)?)", dep)
            if m:
                result.append({"name": m.group(1), "spec": m.group(2).strip() or "*"})
    return result


def _get_installed_version(pkg: str) -> str | None:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None


def _get_latest_version(pkg: str) -> str | None:
    try:
        import urllib.request
        url = f"https://pypi.org/pypi/{pkg}/json"
        req = urllib.request.Request(url, headers={"User-Agent": "laura-check-deps/3.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data["info"]["version"]
    except Exception:
        return None


def _parse_version(ver: str) -> tuple[int, ...]:
    parts = re.split(r"[.\-\s]", ver.split("!")[-1])
    result: list[int] = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            break
    return tuple(result)


def check_deps(path: str | None = None) -> list[dict[str, Any]]:
    pyproject = Path(path) if path else Path.cwd() / "pyproject.toml"
    if not pyproject.exists():
        print(f"Error: {pyproject} not found", file=sys.stderr)
        sys.exit(1)

    deps = _parse_pyproject(pyproject)
    results: list[dict[str, Any]] = []

    for dep in deps:
        name = dep["name"]
        installed = _get_installed_version(name)
        latest = _get_latest_version(name)

        entry: dict[str, Any] = {
            "name": name,
            "spec": dep["spec"],
            "installed": installed,
            "latest": latest,
            "status": "unknown",
        }

        if installed is None:
            entry["status"] = "missing"
        elif latest is None:
            entry["status"] = "unknown"
            entry["latest"] = installed
        elif _parse_version(installed) < _parse_version(latest):
            entry["status"] = "outdated"
        else:
            entry["status"] = "up-to-date"

        results.append(entry)

    return results


def _update_pkg(pkg: str) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", pkg],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode == 0
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check installed package versions and suggest updates")
    parser.add_argument("--path", default="", help="Path to pyproject.toml")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--update-all", action="store_true", help="Update all outdated packages")
    args = parser.parse_args()

    results = check_deps(path=args.path or None)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    outdated: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for r in results:
        status = r["status"]
        installed = r["installed"] or "—"
        latest = r["latest"] or "—"
        if status == "outdated":
            outdated.append(r)
            print(f"OUTDATED  {r['name']:<25} installed={installed:<15} latest={latest}")
        elif status == "missing":
            missing.append(r)
            print(f"MISSING   {r['name']:<25} spec={r['spec']}")
        elif status == "up-to-date":
            print(f"OK        {r['name']:<25} {installed}")
        else:
            print(f"UNKNOWN   {r['name']:<25} installed={installed}")

    total = len(results)
    up_to_date = total - len(outdated) - len(missing)
    print()
    print(f"Total: {total} | Up-to-date: {up_to_date} | Outdated: {len(outdated)} | Missing: {len(missing)}")

    if args.update_all and outdated:
        print()
        print("Updating all outdated packages...")
        for r in outdated:
            print(f"  Updating {r['name']} ({r['installed']} -> {r['latest']})... ", end="", flush=True)
            ok = _update_pkg(r["name"])
            print("OK" if ok else "FAILED")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
