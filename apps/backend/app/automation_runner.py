from __future__ import annotations

import argparse
import signal

from app.services.wechat_mp_automation import WechatMpAutomationScheduler
from app.services.workbench import initialize_store


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the cross-platform WeChat MP draft automation scheduler")
    parser.add_argument("--loop", action="store_true", help="keep polling until interrupted")
    args = parser.parse_args()

    initialize_store()
    scheduler = WechatMpAutomationScheduler()

    def stop_scheduler(_signum: int, _frame) -> None:
        scheduler.stop()

    signal.signal(signal.SIGINT, stop_scheduler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_scheduler)

    if args.loop:
        scheduler.run_forever()
    else:
        scheduler.run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

