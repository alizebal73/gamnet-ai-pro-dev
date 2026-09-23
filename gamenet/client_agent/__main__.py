"""Entry point: python -m gamenet.client_agent [--config agent.json]."""

import argparse
import threading

from gamenet.client_agent.agent import Agent
from gamenet.client_agent.config import AgentConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="GameNet Pro client agent")
    parser.add_argument("--config", default=None,
                        help="Path to agent JSON config file")
    parser.add_argument("--server", default=None)
    parser.add_argument("--device-code", default=None)
    parser.add_argument("--secret", default=None)
    args = parser.parse_args()

    if args.config:
        config = AgentConfig.from_file(args.config)
    else:
        config = AgentConfig.from_env()
    if args.server:
        config.server_url = args.server
    if args.device_code:
        config.device_code = args.device_code
    if args.secret:
        config.secret = args.secret
    config.validate()

    print(f"[agent] {config.device_code} -> {config.server_url} "
          f"(v{config.agent_version})")
    Agent(config).run_forever(threading.Event())


if __name__ == "__main__":
    main()
