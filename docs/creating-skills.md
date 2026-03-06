# Creating Skills

A skill is a Markdown file that teaches the agent a new capability in natural language. Skills are **not executable code** — they are prompt fragments injected into the agent's context when needed. The agent uses its existing tools (file read/write/edit, shell exec) to carry out the skill's instructions.

## Skill Location

Skills live at:

```
~/.munai/workspace/skills/<skill-name>/SKILL.md
```

Each skill is a directory containing at minimum a `SKILL.md` file.

## SKILL.md Format

```markdown
---
name: gmail-checker
description: Check Gmail inbox and summarize unread messages
trigger: /gmail
tags: [email, productivity]
requires:
  env:
    - GMAIL_APP_PASSWORD
  bins:
    - curl
---

# Gmail Checker

When asked to check email, use the Gmail IMAP interface via curl:

1. Connect to imap.gmail.com:993 using the credentials in GMAIL_APP_PASSWORD
2. Fetch unread message headers (Subject, From, Date)
3. Summarize the inbox as a short list
4. Never download full message bodies unless explicitly asked

## Safety

- Never forward, delete, or modify emails unless the user explicitly requests it
- Always confirm before any destructive action
```

### Frontmatter fields

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique identifier (lowercase, hyphens allowed) |
| `description` | Yes | One-line description used in the skills manifest shown to the agent |
| `trigger` | No | Slash command that activates the skill (e.g., `/gmail`) |
| `tags` | No | List of tags for categorization |
| `requires.env` | No | Environment variable names the skill needs to function |
| `requires.bins` | No | System binaries the skill expects (e.g., `curl`, `git`, `python3`) |

## How Skills Are Loaded

1. At startup (and on file change in dev mode), the runtime scans `workspace/skills/*/SKILL.md`.
2. For each skill, it extracts `name` and `description` from the frontmatter.
3. A compact manifest is built: `skill_name: description` (one line per skill).
4. This manifest is injected into the system prompt so the agent knows what skills are available.
5. When the agent needs a skill, it uses `file_read` to load the full `SKILL.md` content.
6. If a message starts with the skill's `trigger`, the full skill content is automatically prepended to the user message.

## Writing Effective Skills

### Be specific about inputs and outputs

```markdown
## Input format

The user will say something like "check my email" or "any new emails?".
Read this as a request to run the Gmail check flow below.

## Output format

Reply with a bulleted list of unread emails:
- **Subject** — From (Date)

If there are no unread emails, say "Your inbox is empty."
```

### Define safety boundaries explicitly

The agent follows safety instructions in the skill file. Be explicit:

```markdown
## Safety rules

- Never run `git push --force` under any circumstances
- Always show a diff before committing
- Confirm the branch name before pushing
```

### Show concrete examples

```markdown
## Example

User: "commit my changes"

Steps:
1. Run `git status` to see what changed
2. Run `git diff --stat` to summarize
3. Ask the user for a commit message if they didn't provide one
4. Run `git add -A && git commit -m "<message>"`
```

### Keep skills focused

One skill should do one thing. A skill that does too much is harder to reason about and harder for the agent to invoke correctly. Split complex workflows into multiple skills.

## Installing Skills

### From the CLI

```bash
munai skills add ./my-skill/        # From a local directory
munai skills add /path/to/SKILL.md  # Single file (placed in skills/my-skill/)
```

Via git URL (requires `git` on PATH):

```bash
munai skills add https://github.com/example/munai-skill-gmail.git
```

### From the WebChat UI

Go to **Skills** in the sidebar, click **Add skill**, and paste a path or git URL.

### Manually

Create the directory and file directly:

```bash
mkdir -p ~/.munai/workspace/skills/my-skill
cat > ~/.munai/workspace/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: Does something useful
---

# My Skill

Instructions here.
EOF
```

## Listing Installed Skills

```bash
munai skills               # List all skills with name, trigger, description
munai skills gmail-checker # Show the full content of a specific skill
```

## Security Considerations

- Skills can only do what the tool policy allows (file scope, shell approval, etc.)
- A skill cannot bypass `workspace_only: true` or `shell_approval_mode: "always"`
- Every tool call made while executing a skill is logged in the audit trail
- Review skill files before installing them — they are prompt text you are trusting

## Example: A Git Commit Skill

```markdown
---
name: commit
description: Stage all changes and create a git commit with an AI-generated message
trigger: /commit
requires:
  bins:
    - git
---

# Commit Skill

When the user runs /commit:

1. Run `git status` to confirm there are staged or unstaged changes
2. If the working tree is clean, report "Nothing to commit"
3. Run `git diff --stat` to summarize what changed
4. Generate a concise commit message (imperative mood, 50 chars max)
5. Run `git add -A` then `git commit -m "<message>"`
6. Show the commit hash and message to the user

## Safety

- Never commit if `git status` shows an empty working tree
- Never use `--no-verify` or `--force`
- Ask for confirmation before committing if the diff is large (>20 files)
```
