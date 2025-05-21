import asyncio
import argparse
import logging
from .exploration_policy import ExplorationAgent

logging.basicConfig(level=logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Web-Explorer on a target URL")
    parser.add_argument("--url", help="Target web app URL to explore")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default)")
    parser.add_argument("--out", default="run_artifacts", help="Directory to save run artefacts")
    parser.add_argument("--max-depth", type=int, default=2, help="Maximum number of distinct abstract states to visit")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum number of actions to execute")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep after each state transition")
    parser.add_argument("--animate", action="store_true", help="Enable animations and visual feedback for actions")
    args = parser.parse_args()

    # If animations are enabled, ensure we're not in headless mode
    if args.animate and args.headless:
        print("Note: --animate flag requires non-headless mode. Disabling headless mode.")
        args.headless = False

    agent = ExplorationAgent(
        start_url=args.url,
        headless=args.headless,
        output_dir=args.out,
        max_depth=args.max_depth,
        max_steps=args.max_steps,
        state_sleep=args.sleep,
        animate_actions=args.animate,  # Pass the animate flag to enable visual feedback
    )
    
    print(f"Starting exploration of {args.url}")
    print(f"Animation mode: {'ENABLED' if args.animate else 'DISABLED'}")
    
    knowledge = asyncio.run(agent.explore())
    print("Exploration finished. Abstract states:", len(knowledge.abstract_states))
    print("Abstract actions:", len(knowledge.abstract_actions))


if __name__ == "__main__":
    main() 