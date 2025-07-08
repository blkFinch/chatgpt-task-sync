#!/usr/bin/env python3
"""
TaskSync – A simple CLI tool to synchronise tasks between Todoist, a local SQLite database,
           and (optionally) an Obsidian markdown file, and to feed today's open tasks to ChatGPT.

Features
--------
1. Database layer (SQLite via sqlite3) that stores tasks and their status.
2. Todoist client to fetch tasks and upsert them into the DB.
3. Obsidian exporter to write a markdown checklist of open tasks (optional).
4. ChatGPT controller that sends the open-task list and retrieves an action-focused summary.
5. CLI interface with subcommands:
       sync-todoist   # fetch & store tasks
       export-md      # write markdown file in Obsidian vault
       ask-chatgpt    # pipe tasks to ChatGPT and print response
Config
------
Set the following environment variables or create a `.env` file in the same directory:
    TODOIST_API_TOKEN   – your personal Todoist token
    OBSIDIAN_VAULT      – absolute path to your Obsidian vault (optional)
    OPENAI_API_KEY      – OpenAI key for chat completion
Usage
-----
    $ python task_sync.py sync-todoist
    $ python task_sync.py export-md
    $ python task_sync.py ask-chatgpt --model gpt-4o
"""
import os
import sqlite3
import json
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import requests
import openai

DB_NAME = "tasks.db"
TODOIST_API = "https://api.todoist.com/rest/v2/tasks"
DATE_FMT = "%Y-%m-%d"

@dataclass
class Task:
    id: int                 # Local DB PK
    external_id: str        # Todoist task ID
    content: str
    due: Optional[str]      # ISO date string
    completed: bool
    source: str = "todoist"

class Database:
    def __init__(self, db_path=DB_NAME):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT UNIQUE,
                content TEXT NOT NULL,
                due TEXT,
                completed INTEGER NOT NULL,
                source TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def upsert_tasks(self, tasks: List['Task']):
        for t in tasks:
            self.conn.execute(
                """
                INSERT INTO tasks (external_id, content, due, completed, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(external_id)
                DO UPDATE SET
                    content=excluded.content,
                    due=excluded.due,
                    completed=excluded.completed
                """,
                (t.external_id, t.content, t.due, int(t.completed), t.source),
            )
        self.conn.commit()

    def get_open_tasks(self) -> List['Task']:
        cur = self.conn.execute(
            "SELECT * FROM tasks WHERE completed=0 ORDER BY due IS NULL, due"
        )
        rows = cur.fetchall()
        return [Task(**dict(r)) for r in rows]

class TodoistClient:
    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def fetch_tasks(self) -> List['Task']:
        resp = self.session.get(TODOIST_API, params={"filter": "active"})
        resp.raise_for_status()
        data = resp.json()
        tasks: List['Task'] = []
        for item in data:
            tasks.append(
                Task(
                    id=0,
                    external_id=item["id"],
                    content=item["content"],
                    due=item["due"]["date"] if item.get("due") else None,
                    completed=item["is_completed"],
                    source="todoist",
                )
            )
        return tasks

class ObsidianExporter:
    def __init__(self, vault_path: str):
        self.vault = vault_path

    def export(self, tasks: List['Task'], filename: Optional[str] = None):
        if not filename:
            filename = datetime.now().strftime("%Y-%m-%d Open Tasks.md")
        md_path = os.path.join(self.vault, filename)
        lines = ["## Open Tasks\n"]
        for t in tasks:
            due_str = f"(due {t.due})" if t.due else ""
            lines.append(f"- [ ] {t.content} {due_str}\n")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        print(f"Wrote {len(tasks)} tasks to {md_path}")

class ChatGPTController:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        openai.api_key = api_key
        self.model = model

    def summarise_tasks(self, tasks: List['Task']) -> str:
        task_lines = [
            f"- {t.content}" + (f" (due {t.due})" if t.due else "")
            for t in tasks
        ]
        prompt = (
            "Here is my current open task list:\n"
            + "\n".join(task_lines)
            + "\n\nPlease tell me what I need to focus on today. "
              "Prioritise by urgency and importance, and keep it concise."
        )
        resp = openai.ChatCompletion.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message["content"]

def load_env():
    from pathlib import Path
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

def main():
    load_env()
    parser = argparse.ArgumentParser(description="TaskSync CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync-todoist")
    sub.add_parser("export-md")
    parser_chat = sub.add_parser("ask-chatgpt")
    parser_chat.add_argument("--model", default="gpt-4o")

    args = parser.parse_args()
    db = Database()

    if args.cmd == "sync-todoist":
        token = os.getenv("TODOIST_API_TOKEN")
        if not token:
            raise SystemExit("TODOIST_API_TOKEN missing")
        client = TodoistClient(token)
        tasks = client.fetch_tasks()
        db.upsert_tasks(tasks)
        print(f"Synced {len(tasks)} tasks from Todoist.")
    elif args.cmd == "export-md":
        vault = os.getenv("OBSIDIAN_VAULT")
        if not vault:
            raise SystemExit("OBSIDIAN_VAULT missing")
        exporter = ObsidianExporter(vault)
        tasks = db.get_open_tasks()
        exporter.export(tasks)
    elif args.cmd == "ask-chatgpt":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise SystemExit("OPENAI_API_KEY missing")
        controller = ChatGPTController(api_key=key, model=args.model)
        tasks = db.get_open_tasks()
        summary = controller.summarise_tasks(tasks)
        print(summary)

if __name__ == "__main__":
    main()
