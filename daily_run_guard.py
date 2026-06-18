#!/usr/bin/env python3
"""Prevent duplicate automated daily workflow runs for the same Hong Kong day."""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


AUTOMATED_EVENTS = {"schedule", "repository_dispatch"}
DEFAULT_API_URL = "https://api.github.com"
DEFAULT_WORKFLOW = "daily_run.yml"
HONG_KONG_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Decision:
    skip: bool
    reason: str


def _parse_github_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def should_skip(event_name, runs, current_run_id, now, target_tz=HONG_KONG_TZ):
    """Return whether this automated run should stop because today already succeeded."""
    if event_name not in AUTOMATED_EVENTS:
        return Decision(False, f"{event_name} event bypasses duplicate guard")

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    target_date = now.astimezone(target_tz).date()
    current_run_id = str(current_run_id)

    for run in runs:
        if str(run.get("id")) == current_run_id:
            continue
        if run.get("conclusion") != "success":
            continue
        created_at = run.get("created_at")
        if not created_at:
            continue

        try:
            run_date = _parse_github_time(created_at).astimezone(target_tz).date()
        except ValueError:
            continue

        if run_date == target_date:
            run_id = run.get("id", "unknown")
            run_event = run.get("event", "unknown")
            return Decision(
                True,
                f"successful run {run_id} ({run_event}) already completed on {target_date.isoformat()}",
            )

    return Decision(False, f"no successful run found for {target_date.isoformat()}")


def fetch_workflow_runs(api_url, repo, workflow, token):
    workflow_path = urllib.parse.quote(workflow, safe="")
    repo_path = urllib.parse.quote(repo, safe="/")
    url = (
        f"{api_url.rstrip('/')}/repos/{repo_path}/actions/workflows/"
        f"{workflow_path}/runs?status=completed&per_page=100"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return payload.get("workflow_runs", [])


def write_github_output(output_path, decision):
    if not output_path:
        return
    reason = decision.reason.replace("\r", " ").replace("\n", " ")
    skip = "true" if decision.skip else "false"
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"skip={skip}\n")
        output.write(f"reason={reason}\n")


def _decision_from_env(args, env):
    event_name = args.event_name or env.get("GITHUB_EVENT_NAME", "")
    current_run_id = args.run_id or env.get("GITHUB_RUN_ID", "")

    if event_name not in AUTOMATED_EVENTS:
        return should_skip(event_name, [], current_run_id, datetime.now(timezone.utc))

    repo = args.repo or env.get("GITHUB_REPOSITORY")
    token = args.token or env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
    if not repo:
        return Decision(False, "GITHUB_REPOSITORY is not set; allowing run")
    if not token:
        return Decision(False, "GITHUB_TOKEN is not set; allowing run")

    try:
        runs = fetch_workflow_runs(
            api_url=args.api_url,
            repo=repo,
            workflow=args.workflow,
            token=token,
        )
    except Exception as exc:
        return Decision(False, f"guard check failed ({exc}); allowing run")

    return should_skip(
        event_name=event_name,
        runs=runs,
        current_run_id=current_run_id,
        now=datetime.now(timezone.utc),
    )


def main(argv=None, env=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--repo")
    parser.add_argument("--token")
    parser.add_argument("--event-name")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    env = os.environ if env is None else env
    decision = _decision_from_env(args, env)
    write_github_output(env.get("GITHUB_OUTPUT"), decision)
    print(f"skip={'true' if decision.skip else 'false'}")
    print(decision.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
