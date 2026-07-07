from __future__ import annotations

import argparse

from carebridge.agents import pretty_json, run_carebridge_agent


SAMPLE_TEXT = (
    "My work hours were cut, rent is due Friday, and I need groceries for two kids. "
    "My phone is 512-555-0188 and email is alex@example.com."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CareBridge Agent demo.")
    parser.add_argument("--text", help="Situation to analyze.")
    parser.add_argument("--location", default="Austin, TX", help="City and state, such as 'Austin, TX'.")
    parser.add_argument("--household-size", type=int, default=3)
    parser.add_argument("--language", default="English")
    parser.add_argument("--sample", action="store_true", help="Run a sample hardship case.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    text = SAMPLE_TEXT if args.sample or not args.text else args.text
    plan = run_carebridge_agent(
        {
            "text": text,
            "location": args.location,
            "household_size": args.household_size,
            "language": args.language,
        }
    )
    print(pretty_json(plan))


if __name__ == "__main__":
    main()

