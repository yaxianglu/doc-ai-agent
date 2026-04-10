from __future__ import annotations

import os
import sys

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import build_app


def main() -> int:
    config = AppConfig.from_env(os.environ)
    if not config.db_url:
        print("DOC_AGENT_DB_URL 未配置，无法导入 MySQL")
        return 1
    app = build_app(config)
    result = app.refresh()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
