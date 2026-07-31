#!/usr/bin/env python3
"""CI monitor: watches specified branches' workflow runs, retries failed runs up to 3 times,
captures failed logs, and files issues for persistent failures.
"""
import json
import os
import shlex
import subprocess
import time
from typing import Dict, Any

REPO = "Meketref007/Laura"
BRANCHES = ["fix/load-sidecar-vectors", "chore/trigger-ci-noop"]
STATE_FILE = "/tmp/ci_monitor_state.json"
POLL_INTERVAL = 300
MAX_RERUN = 3


def run(cmd: str) -> str:
    p = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
    if p.returncode != 0:
        return p.stderr.strip()
    return p.stdout.strip()


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, Any]) -> None:
    try:
        with open(STATE_FILE, "w") as fh:
            json.dump(state, fh)
    except Exception:
        pass


def fetch_runs_for_branch(branch: str):
    cmd = f"gh api repos/{REPO}/actions/runs?branch={branch}&per_page=5"
    out = run(cmd)
    try:
        data = json.loads(out)
        return data.get("workflow_runs", [])
    except Exception:
        return []


def capture_failed_logs(run_id: int) -> str:
    path = f"/tmp/ci_run_{run_id}_failed.txt"
    cmd = f"gh run view {run_id} --log-failed --repo {REPO}"
    out = run(cmd)
    try:
        with open(path, "w") as fh:
            fh.write(out)
    except Exception:
        pass
    return path


def create_issue(title: str, body: str) -> None:
    cmd = f"gh issue create --repo {REPO} --title {shlex.quote(title)} --body {shlex.quote(body)}"
    run(cmd)


def rerun_run(run_id: int) -> bool:
    cmd = f"gh run rerun {run_id} --repo {REPO}"
    out = run(cmd)
    return "Requested rerun" in out or out == ""


def handle_failed_run(run: Dict[str, Any], state: Dict[str, Any]) -> None:
    run_id = str(run.get("id"))
    key = f"run_{run_id}"
    retries = state.get(key, 0)
    if retries < MAX_RERUN:
        success = rerun_run(run.get("id"))
        state[key] = retries + (1 if success else 0)
        save_state(state)
    else:
        # persistent failure: capture logs and open an issue
        logs_path = capture_failed_logs(run.get("id"))
        title = f"Persistent CI failure: run {run.get('id')} on branch {run.get('head_branch')}"
        body = (
            f"Workflow run {run.get('html_url')} failed repeatedly on branch {run.get('head_branch')}.\n\n"
            f"Logs saved to: {logs_path}\n\nPlease triage and assign."
        )
        create_issue(title, body)
        # mark as handled to avoid repeated issues
        state[key] = retries + 1
        save_state(state)


def main():
    state = load_state()
    # Maximum runtime in seconds. Set to 0 for indefinite.
    try:
        max_seconds = int(os.environ.get("MONITOR_MAX_SECONDS", str(24 * 3600)))
    except Exception:
        max_seconds = 24 * 3600
    start_time = time.time()
    while True:
        # Exit after configured max runtime (if > 0)
        try:
            if max_seconds > 0 and (time.time() - start_time) > max_seconds:
                print(f"CI monitor reached max runtime ({max_seconds}s), exiting.")
                save_state(state)
                return
        except Exception:
            pass

        for branch in BRANCHES:
            runs = fetch_runs_for_branch(branch)
            for run in runs:
                if run.get("status") == "completed" and run.get("conclusion") in ("failure", "cancelled", "timed_out"):
                    handle_failed_run(run, state)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
