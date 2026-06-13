# PDF to PPT Generator

See `.cursor/rules/project.mdc` for project layout and run commands.

## Stack

- **Backend**: Python, FastAPI, Gemini agents, python-pptx pipeline
- **Frontend**: Next.js

## Key paths

- Pipeline: `backend/pipeline/orchestrator.py`
- Agents: `backend/agents/`
- API: `backend/app.py`
- PPT assets: `backend/assets/reference_ppts/`

## Do not commit

- `.env`, `.venv/`, `uploads/`, `outputs/`
- `.claude/settings.local.json` (local Claude Code permissions)
