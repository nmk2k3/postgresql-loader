# AGENTS.md

## Project Context
- Python application that loads Tiki JSON data into PostgreSQL.
- PostgreSQL runs in Docker.
- Python runs directly on Ubuntu/WSL.

## Coding Guidelines
- Keep code simple and readable.
- Prefer functions over unnecessary classes.
- Avoid overengineering.
- Use parameterized SQL queries.
- Keep dependencies minimal.
- Appropriate comments for coding reviews

## Project Constraints
- Do not modify source JSON files.
- Do not containerize Python.
- Do not commit credentials or datasets.

## Agent Workflow
- Review existing code before making changes.
- Explain the implementation plan before coding.
- Make minimal changes.
- Test changes before reporting completion.
- Do not push to GitHub without permission.