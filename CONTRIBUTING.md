# Contributing Guidelines

## Development Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/<your-username>/livesubs.git
   cd livesubs
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Add your GROQ_API_KEY
   ```

4. Start local Valkey instance:
   ```bash
   docker run -d --name valkey -p 6379:6379 valkey/valkey:7.2-alpine
   ```

---

## Validation Before Submitting

Always verify local execution and tests before submitting a pull request:

```bash
# Verify syntax and compilation across modules
./venv/bin/python -m py_compile backend/server.py backend/worker.py backend/database.py backend/exporters.py scripts/simulate_sessions.py

# Verify gateway startup
./venv/bin/python backend/server.py &
SERVER_PID=$!
sleep 2
curl -f http://localhost:8000/health
kill $SERVER_PID

# Verify worker execution with an audio file
./venv/bin/python backend/worker.py --file path/to/test.wav
```

---

## Commit Guidelines

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

- `feat: <description>` (new functionality)
- `fix: <description>` (bug fix)
- `perf: <description>` (performance improvement)
- `refactor: <description>` (code restructuring without behavioral changes)
- `docs: <description>` (documentation updates)
- `test: <description>` (adding or modifying tests)

Keep commit messages concise, imperative, and focused on the change rationale.

---

## Pull Request Requirements

1. Target branch: `main` or the active feature release branch.
2. Provide a clear description of:
   - The bug fixed or feature implemented.
   - Exact steps and tests executed to verify the change.
   - Any API or configuration changes.
3. Keep pull requests focused on a single concern. Avoid mixing unrelated formatting or refactoring changes.

---

## Bug Reports

Open an issue on GitHub with:
1. OS and version (Linux, macOS, Windows).
2. Python and Docker version.
3. Steps to reproduce the issue.
4. Error tracebacks and relevant console logs from `server` or `worker`.
5. Expected vs actual behavior.
