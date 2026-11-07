# Getting started (on your laptop)

This gets Parallax running on your Mac in about 20 minutes. No server needed yet.

## 1. Tools

You need **uv**, which installs Python and all libraries for you. Check whether you have it:

```bash
uv --version
```

If that prints "command not found", install it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then close and reopen the terminal.

## 2. Install Parallax's libraries

From the project folder:

```bash
uv sync
```

This creates a `.venv` folder with everything inside. You never need to "activate" it: prefix commands with `uv run`.

## 3. An Anthropic API key, with spending limits

Parallax uses Anthropic's models through the **API**, which is billed per use. A Claude.ai Pro or Max subscription does **not** include API access, so you don't need one.

1. Go to **platform.claude.com** (the Claude Console) and create an account.
2. **Billing → buy prepaid credits**, e.g. $20. Leave **auto-reload off**. Then you can never be charged more than what you prepaid.
3. **Limits**: set a monthly spend limit for the organisation, e.g. $60.
4. **Workspaces**: create a workspace named `parallax` and give it its own spend limit, e.g. $50.
5. **API keys**: inside the `parallax` workspace, create a key named `parallax-laptop`. Copy it; it is shown only once.

Make your settings file and paste the key in:

```bash
cp .env.example .env
open -e .env        # opens it in TextEdit; paste the key after ANTHROPIC_API_KEY=
```

`.env` is never committed or uploaded by the scripts. Treat the key like a password. If it ever leaks, delete it in the Console and create a new one.

Parallax adds its own limit: `PARALLAX_MONTHLY_BUDGET_USD` in `.env` (default 40). Every AI call is logged with its cost, and the pipeline stops calling the AI once the month's total reaches that number. So there are three layers: prepaid credits, the Console limits, and Parallax's budget guard.

## 4. First run

Fetch statements (no AI, costs nothing):

```bash
uv run parallax collect
uv run parallax sources      # which sources worked
```

Then the AI steps and the website:

```bash
uv run parallax run
uv run parallax costs        # what that cost
uv run parallax serve        # open http://localhost:8000 in your browser
```

The first run reads up to 15 statements per source and costs roughly $0.50–$2. Events need statements from at least two actors before they are compared, so the site gets more interesting after a few days of collection.

## 5. Next

- Put it on a server: [deployment.md](deployment.md)
- The daily and weekly routine: [operations.md](operations.md)
