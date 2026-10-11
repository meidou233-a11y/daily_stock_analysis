"""Prepare a bounded, ephemeral stock pool for the daily Actions task."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(market, output):
    import yaml
    from src.services.auto_stock_pool import fetch_market_snapshot, screen_snapshot, foreign_history
    from src.services.screening.config import Config
    profiles = yaml.safe_load(Path(os.getenv("AUTO_SCREEN_CONFIG", ROOT / "config/auto-screening.yaml")).read_text())
    config = Config.from_env()
    snapshot = fetch_market_snapshot(market, config, int(os.getenv("AUTO_SCREEN_UNIVERSE_LIMIT", "50")))
    def checkpoint(rows, warnings):
        path = Path(output)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"candidates": rows, "warnings": warnings}, ensure_ascii=False))
        temporary.replace(path)

    rows, warnings = screen_snapshot(snapshot, market, profiles["markets"][market],
                                    daily_limit=int(os.getenv("AUTO_SCREEN_DAILY_LIMIT", "5")),
                                    history_fetcher=foreign_history if market != "cn" else None, checkpoint=checkpoint)
    checkpoint(rows, warnings)


def prepare(output):
    from src.services.auto_stock_pool import merge_daily_pool
    pools, warnings = {}, []
    try:
        limit = max(0, min(20, int(os.getenv("AUTO_SCREEN_MAX_ADDITIONS", "5"))))
    except ValueError:
        limit = 5
        warnings.append("Invalid AUTO_SCREEN_MAX_ADDITIONS; using default 5")
    enabled = os.getenv("AUTO_SCREEN_ENABLED", "false").lower() == "true"
    if enabled:
        for market in os.getenv("AUTO_SCREEN_MARKETS", "cn,hk,us").split(","):
            market = market.strip()
            with tempfile.TemporaryDirectory() as folder:
                result_path = str(Path(folder) / "result.json")
                try:
                    process = subprocess.run([sys.executable, __file__, "--market", market, "--output", result_path],
                                             timeout=float(os.getenv("AUTO_SCREEN_MARKET_TIMEOUT", "90")),
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    if process.returncode != 0:
                        raise RuntimeError("screening worker failed")
                    result = json.loads(Path(result_path).read_text())
                    pools[market] = result["candidates"]
                    warnings.extend(result["warnings"])
                except (subprocess.TimeoutExpired, RuntimeError, OSError, ValueError, KeyError) as exc:
                    warnings.append(f"{market}: {type(exc).__name__}; fixed watchlist retained")
                    # Keep completed styles even if the daily-history style timed out.
                    if Path(result_path).exists():
                        try:
                            partial = json.loads(Path(result_path).read_text())
                            pools[market] = partial["candidates"]
                            warnings.extend(partial["warnings"])
                        except (OSError, ValueError, KeyError, TypeError):
                            warnings.append(f"{market}: unreadable partial screening result")
    codes, added = merge_daily_pool(os.getenv("STOCK_LIST", ""), os.getenv("STOCK_LIST_EXTRA", ""), pools,
                                  limit=limit)
    if not codes:
        raise ValueError("Empty stock pool")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(",".join(codes))
    Path(output).with_suffix(".json").write_text(json.dumps({"added": added, "warnings": warnings}, ensure_ascii=False, indent=2))
    print(f"Daily pool: {len(codes)} stocks; {len(added)} automatic additions")
    for warning in warnings:
        print(f"::warning::{warning}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--market")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.market:
        worker(args.market, args.output)
    else:
        prepare(args.output)
