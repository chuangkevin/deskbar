# Cinematic scene redesign — checkpoint handoff

## Checkpoint

- Branch: `cinematic-scene-redesign`
- Baseline: `93d73bf`
- This is an **unfinished checkpoint**, intentionally not pushed to `build/v1` and not deployed.
- The local approved execution plan remains under `.omo/plans/cinematic-scene-redesign.md`; `.omo/` stays ignored and is not deployed.

## Completed

- Plan Todos 1–10: design contract, typed runtime, split renderers, bounded active assets, review/benchmark tools, and all five scene lanes.
- Ten public scene keys/order and `scene_tap` contract remain unchanged.
- Production asset set contains 81 deterministic PNGs. Two clean generator runs matched byte-for-byte, and production now matches that manifest.
- Current lane metrics satisfy their material, color, motion, deterministic replay, alpha-edge, and ≤48 MiB decoded-asset contracts.
- Latest focused suites run during implementation are green; basedpyright remains unavailable because installation was previously declined.

## Remaining before `build/v1`

1. Finish Todo 11 focused integration tests and mark it complete.
2. Todo 12: regenerate all-scene fresh visual evidence and obtain required non-Oracle approvals.
3. Todo 13: full pytest, compileall, all-scene benchmark, cache/RSS cycle, source/LOC guards, and diagnostics record.
4. Todo 14: build the planned nine atomic Traditional-Chinese commits on the final branch, then normal-push `build/v1` only after all local gates pass.
5. Todo 15: deploy to the configured Pi, verify service/screenshot/RSS, run 20+120 frames for all ten scenes with p95 ≤80 ms, and restore the original `force` + `stars` preference.
6. Run final F1–F4 non-Oracle reviews.

## Resume

```bash
cd /Users/ching/Documents/Projects/deskbar
opencode
```

Resume the Boulder worktree at `/Users/ching/Documents/Projects/deskbar-cinematic-worktree`. Do not re-plan, force-push, commit `.omo`, or deploy before the remaining local gates pass.
