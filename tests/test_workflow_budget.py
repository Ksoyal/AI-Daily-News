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


def test_fallback_shares_four_call_budget_and_is_explicitly_configured():
    from config import AI_FAILOVER_RETRY_DELAYS
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/daily_run.yml").read_text()
    timeout_minutes = int(re.search(r"timeout-minutes: (\d+)", workflow).group(1))
    assert 2 * (len(AI_FAILOVER_RETRY_DELAYS) + 1) == 4
    ai_budget = 4 * 180 + 2 * sum(AI_FAILOVER_RETRY_DELAYS)
    assert ai_budget == 14 * 60
    assert timeout_minutes * 60 >= ai_budget + 20 * 60
    assert "AI_FALLBACK_MODEL: ${{ vars.AI_FALLBACK_MODEL }}" in workflow
