#!/usr/bin/env python3
"""精准触发 GitHub Actions workflow（repository_dispatch）。

用法：
    python trigger.py                          # 用 gh CLI token 自动鉴权
    python trigger.py --token ghp_xxxx         # 手动指定 PAT
    python trigger.py --dry-run                # 只打印不发请求

配合外部免费 cron 服务（Vercel Cron / cron-job.org / 腾讯云函数）
每日北京时间 8:00 执行本脚本即可准时触发。
"""
import os
import sys
import json
import subprocess
import urllib.request

REPO = "Ksoyal/AI-Daily-News"
EVENT = "daily_trigger"


def get_token():
    """Try to get a GitHub PAT: env var → gh CLI → prompt."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def trigger(token, dry_run=False):
    url = f"https://api.github.com/repos/{REPO}/dispatches"
    data = json.dumps({"event_type": EVENT}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    if dry_run:
        print(f"[DRY-RUN] Would POST to {url} with event={EVENT}")
        return True

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (204, 200):
                print(f"[OK] Workflow triggered ({resp.status}) — 去看 Actions 面板")
                return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[FAIL] HTTP {e.code}: {body}")
        return False


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    token = None
    for arg in sys.argv[1:]:
        if arg.startswith("--token="):
            token = arg.split("=", 1)[1]
        elif arg == "--token":
            idx = sys.argv.index("--token")
            token = sys.argv[idx + 1]

    if not token:
        token = get_token()

    if not token:
        print("[FAIL] 没有 GitHub Token。请：\n"
              "  1. 确认已登录 gh CLI (运行 gh auth login)\n"
              "  2. 或设置 GITHUB_TOKEN 环境变量\n"
              "  3. 或 python trigger.py --token ghp_xxxx")
        sys.exit(1)

    success = trigger(token, dry_run=dry_run)
    sys.exit(0 if success else 1)
