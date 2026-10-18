"""Create only a disposable repository and user inside the acceptance project's volume."""

import json
from pathlib import Path

from sentinel.core.configuration.config import load_settings
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store

root = Path("/repos/acceptance")
root.mkdir()
(root / "query.py").write_text(
    "from helper import label\ndef query(cur, name):\n"
    "    return cur.execute(f\"SELECT * FROM users WHERE name = '{name}'\")\n"
)
(root / "helper.py").write_text("def label():\n    return 'unsafe'\n")
(root / "unsafe.ts").write_text(
    "export function unsafe(value: string): unknown { return eval(value); }\n"
)
(root / "unsafe.js").write_text("export function unsafe(value) { return eval(value); }\n")
(root / "tsconfig.json").write_text(
    '{"compilerOptions":{"noEmit":true,"strict":true},"include":["*.ts"]}\n'
)
(root / ".sentinel.yml").write_text("fix:\n  context_files: [helper.py]\n  timeout_s: 60\n")
database = Database(load_settings().database_url)
with database.transaction() as session:
    user, token = Store(session).create_user("compose-acceptance")
print(json.dumps({"user_id": user.id, "token": token}))
