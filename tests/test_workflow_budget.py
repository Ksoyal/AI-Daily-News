"""Keep the production workflow timeout aligned with the default retry budget."""
import re
from pathlib import Path

from config import AI_RETRY_DELAYS


def test_workflow_allows_delayed_retries_and_pipeline_overhead():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/daily_run.yml").read_text()
    timeout_minutes = int(re.search(r"timeout-minutes: (\d+)", workflow).group(1))
    # Default per-request timeout, independent of the runner's env overrides.
    ai_budget = (len(AI_RETRY_DELAYS) + 1) * 180 + sum(AI_RETRY_DELAYS)
    assert timeout_minutes * 60 >= ai_budget + 20 * 60
    # Manual, cron and dispatch runs share the existing serialization lock.
    assert "group: daily-run" in workflow
    assert "cancel-in-progress: false" in workflow
