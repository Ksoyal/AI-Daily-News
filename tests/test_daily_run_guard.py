import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import daily_run_guard


class TestShouldSkip:
    def test_schedule_skips_when_successful_run_already_completed_today(self):
        now = datetime(2026, 6, 18, 2, 30, tzinfo=timezone.utc)
        runs = [
            {
                "id": 100,
                "conclusion": "success",
                "created_at": "2026-06-18T00:04:34Z",
                "event": "repository_dispatch",
            }
        ]

        decision = daily_run_guard.should_skip(
            event_name="schedule",
            runs=runs,
            current_run_id=200,
            now=now,
        )

        assert decision.skip is True
        assert "100" in decision.reason

    def test_schedule_runs_when_success_was_on_previous_hong_kong_day(self):
        now = datetime(2026, 6, 18, 0, 5, tzinfo=timezone.utc)
        runs = [
            {
                "id": 100,
                "conclusion": "success",
                "created_at": "2026-06-17T15:55:00Z",
                "event": "repository_dispatch",
            }
        ]

        decision = daily_run_guard.should_skip(
            event_name="schedule",
            runs=runs,
            current_run_id=200,
            now=now,
        )

        assert decision.skip is False
        assert "no successful run" in decision.reason

    def test_schedule_runs_when_same_day_run_failed(self):
        now = datetime(2026, 6, 18, 2, 30, tzinfo=timezone.utc)
        runs = [
            {
                "id": 100,
                "conclusion": "failure",
                "created_at": "2026-06-18T00:04:34Z",
                "event": "repository_dispatch",
            }
        ]

        decision = daily_run_guard.should_skip(
            event_name="schedule",
            runs=runs,
            current_run_id=200,
            now=now,
        )

        assert decision.skip is False

    def test_repository_dispatch_skips_when_successful_run_already_completed_today(self):
        now = datetime(2026, 6, 18, 2, 30, tzinfo=timezone.utc)
        runs = [
            {
                "id": 100,
                "conclusion": "success",
                "created_at": "2026-06-18T00:00:34Z",
                "event": "schedule",
            }
        ]

        decision = daily_run_guard.should_skip(
            event_name="repository_dispatch",
            runs=runs,
            current_run_id=200,
            now=now,
        )

        assert decision.skip is True

    def test_workflow_dispatch_is_never_skipped(self):
        now = datetime(2026, 6, 18, 2, 30, tzinfo=timezone.utc)
        runs = [
            {
                "id": 100,
                "conclusion": "success",
                "created_at": "2026-06-18T00:04:34Z",
                "event": "schedule",
            }
        ]

        decision = daily_run_guard.should_skip(
            event_name="workflow_dispatch",
            runs=runs,
            current_run_id=200,
            now=now,
        )

        assert decision.skip is False
        assert "workflow_dispatch" in decision.reason

    def test_current_run_is_ignored(self):
        now = datetime(2026, 6, 18, 2, 30, tzinfo=timezone.utc)
        runs = [
            {
                "id": 200,
                "conclusion": "success",
                "created_at": "2026-06-18T02:29:59Z",
                "event": "schedule",
            }
        ]

        decision = daily_run_guard.should_skip(
            event_name="schedule",
            runs=runs,
            current_run_id=200,
            now=now,
        )

        assert decision.skip is False


class TestGitHubApi:
    def test_fetch_workflow_runs_uses_token_and_decodes_runs(self, monkeypatch):
        requests = []

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"workflow_runs": [{"id": 123}]}).encode("utf-8")

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        monkeypatch.setattr(daily_run_guard.urllib.request, "urlopen", fake_urlopen)

        runs = daily_run_guard.fetch_workflow_runs(
            api_url="https://api.github.example",
            repo="owner/repo",
            workflow="daily_run.yml",
            token="token-123",
        )

        request, timeout = requests[0]
        assert runs == [{"id": 123}]
        assert timeout == 15
        assert request.full_url == (
            "https://api.github.example/repos/owner/repo/"
            "actions/workflows/daily_run.yml/runs?status=completed&per_page=100"
        )
        assert request.get_header("Authorization") == "Bearer token-123"


class TestOutput:
    def test_write_github_output_writes_skip_and_reason(self, tmp_path):
        output_file = tmp_path / "github_output.txt"
        decision = daily_run_guard.Decision(skip=True, reason="already ran")

        daily_run_guard.write_github_output(str(output_file), decision)

        assert output_file.read_text(encoding="utf-8") == (
            "skip=true\nreason=already ran\n"
        )
