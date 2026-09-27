"""Tool-trace evaluation of the MCP server (SPEC, "Evaluation").

An LLM gets each task's prompt and the server's tools; the harness records every tool call and
checks the trace, never the prose. Run by hand or nightly, never on pull requests:

    uv run --env-file .env python -m evals.run_eval
"""
