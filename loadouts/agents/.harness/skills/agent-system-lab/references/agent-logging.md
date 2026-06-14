# Agent Logging

## First Principle

Inspect the existing logging or tracing system before recommending changes. Preserve effective conventions, storage, correlation ids, redaction, and dashboards. Add only the missing pieces needed for reliable debugging, eval grading, and improvement.

## Recommended Default

Use two complementary log layers.

### Full Trace Log

Capture every LLM call related to the agent:

- timestamp
- environment
- run/session/conversation/scenario id
- user id or anonymized subject id when appropriate
- model and provider
- input messages or prompt/template references
- available tool names and schemas or schema version
- knowledge source configuration or retrieval parameters
- raw model output
- structured parsed output
- token usage, cost, latency, finish reason, and retries when available
- errors, refusals, timeouts, and safety events

Prefer append-only JSONL, structured event tables, or an existing observability backend. Redact secrets by default. For sensitive user content, store references, hashes, summaries, or encrypted payloads when full text is not required.

### Structured Summary Log

Capture a compact event stream for each agent run:

- user request received
- planning or routing decisions
- tool calls and results
- knowledge/retrieval calls and selected sources
- external API calls
- state reads and writes
- user confirmations or clarification requests
- validation failures and retries
- final response and outcome

This log should be easy to scan, query, and attach to eval reports. It should not require reading full prompts to understand what happened.

## Correlation

Every eval scenario and user run should have a stable correlation id that links:

- scenario definition
- live LLM calls
- tool and knowledge calls
- state snapshots or diffs
- final response
- grading result

Without this chain, failures are too expensive to diagnose and improvements become guesswork.

## Using Logs

Use logs to:

- debug failed evals
- discover new real-user scenarios
- find unused or low-value tools
- identify repeated retries, context bloat, or missing knowledge
- measure whether changes improve reliability and efficiency

Treat missing logs as an agent-system defect when they prevent evaluation, root-cause analysis, or regression prevention.
