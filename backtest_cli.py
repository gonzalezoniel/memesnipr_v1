import argparse
import sys

from src.backtest import (
    BacktestRunner,
    generate_synthetic_scenarios,
    load_scenarios_from_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MEMESNIPR Backtest CLI - replay historical/synthetic scenarios"
    )
    parser.add_argument(
        "--scenarios-file",
        type=str,
        default=None,
        help="Path to JSON file with backtest scenarios (uses synthetic data if omitted)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of synthetic scenarios to generate (ignored if --scenarios-file is set)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for paper broker (default: 42)",
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=1.0,
        help="Simulated wallet balance in SOL (default: 1.0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable summary",
    )
    args = parser.parse_args()

    if args.scenarios_file:
        scenarios = load_scenarios_from_json(args.scenarios_file)
    else:
        scenarios = generate_synthetic_scenarios(count=args.count)

    runner = BacktestRunner(
        broker_seed=args.seed,
        wallet_balance_sol=args.balance,
    )

    report = runner.run(scenarios)

    if args.json:
        import json
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
    else:
        print(report.format_summary())


if __name__ == "__main__":
    main()
