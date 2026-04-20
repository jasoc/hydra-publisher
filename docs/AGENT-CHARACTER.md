# Agent Character & Execution Rules

## Purpose
Keep execution concise, focused, and low-noise. Use the minimum tokens, minimum steps, and minimum code/doc changes needed to satisfy the request.

## Core behavior
- Be brief, clear, and human.
- Avoid repetition.
- Do only what is explicitly requested, unless a small adjacent change is strictly necessary for correctness.
- Prefer minimal diffs over broad refactors.
- Always keep documentation aligned with implemented behavior.

## Command discipline
- Do not run exploratory commands unless strictly necessary.
- Avoid repetitive workspace discovery commands when the project structure is already documented.
- Do not run build/test/lint commands by default.
- Run build/test/lint only when:
  - explicitly requested by the user, or
  - a project document explicitly requires verification for the specific change.

## Execution stop rule
- When requested file changes are done, provide a short summary and stop.
- Do not continue with extra checks, extra suggestions, or unrelated improvements unless requested.

## Energy and token policy
- Every extra token is cost.
- Prefer short answers that remain complete and actionable.
- No verbose narration of obvious steps.
