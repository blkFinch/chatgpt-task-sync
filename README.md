# Task Sync

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install requests openai python-dotenv
```

### create .env

```
TODOIST_API_TOKEN=your-todoist-token
OPENAI_API_KEY=your-openai-key
OBSIDIAN_VAULT=/absolute/path/to/your/vault   # optional
```

## Running

```
python task_sync.py sync-todoist
```

## Daily Workflow

```
# Write an “Open Tasks” note inside Obsidian
python task_sync.py export-md

# Get ChatGPT to triage what matters today
python task_sync.py ask-chatgpt
```
