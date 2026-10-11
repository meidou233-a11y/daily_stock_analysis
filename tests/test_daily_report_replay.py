"""Exercise the workflow's actual artifact staging shell against gh layouts."""
from pathlib import Path
import subprocess

import pytest
import yaml


@pytest.mark.parametrize("layout", ["reports", "analysis-reports-22/reports"])
def test_replay_stages_flat_and_named_artifacts(tmp_path, layout):
    source = tmp_path / "reports-replay" / layout
    source.mkdir(parents=True)
    for name in ("report_20261011.md", "market_review_20261011.md", "daily_stock_pool.json"):
        (source / name).write_text(name, encoding="utf-8")
    result = run_staging(tmp_path)
    assert result.returncode == 0, result.stderr
    for path in source.iterdir():
        assert (tmp_path / "reports" / path.name).read_bytes() == path.read_bytes()


@pytest.mark.parametrize("layouts", [[], ["a/reports", "b/reports"]])
def test_replay_rejects_missing_or_ambiguous_reports(tmp_path, layouts):
    (tmp_path / "reports-replay").mkdir()
    for layout in layouts:
        (tmp_path / "reports-replay" / layout).mkdir(parents=True)
    result = run_staging(tmp_path)
    assert result.returncode != 0
    assert "Expected exactly one saved reports directory" in result.stdout
    assert not list((tmp_path / "reports").iterdir())


def run_staging(tmp_path):
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/00-daily-analysis.yml").read_text())
    step = next(s for s in workflow["jobs"]["analyze"]["steps"] if s.get("name") == "执行股票分析")
    shell = step["run"].split("--dir reports-replay\n", 1)[1].split("python scripts/send_daily_notifications.py", 1)[0]
    return subprocess.run(["bash", "-e", "-c", shell], cwd=tmp_path, capture_output=True, text=True)
