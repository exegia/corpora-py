# Tigris Agent Kit

This skill helps Claude build storage workflows for AI agents on Tigris using `@tigrisdata/agent-kit`.

## What It Covers

`@tigrisdata/agent-kit` composes lower-level `@tigrisdata/storage` and `@tigrisdata/iam` primitives into four building blocks for agent infrastructure:

- **Forks** — N isolated copy-on-write copies of a shared dataset, one per agent
- **Workspaces** — Dedicated per-agent buckets with optional TTL and scoped credentials
- **Checkpoints** — Snapshot bucket state, restore as an independent fork
- **Coordination** — Event-driven multi-agent pipelines via bucket webhooks

## Installation

### Claude Code

```bash
cp -r skills/tigris-agent-kit ~/.claude/skills/
```

### claude.ai

Add `SKILL.md` and the `resources/` directory to your project knowledge.

## Usage

Claude activates this skill automatically. Trigger phrases include:

- "Set up isolated storage for these agents"
- "Fork this dataset for parallel runs"
- "Create a workspace for this agent"
- "Checkpoint this bucket"
- "Restore from this checkpoint"
- "Wire up a webhook when objects land in this bucket"
- "Build a multi-agent pipeline on Tigris"

## Quick Reference

| Building Block | Functions |
|---|---|
| Forks | `createForks`, `teardownForks` |
| Workspaces | `createWorkspace`, `teardownWorkspace` |
| Checkpoints | `checkpoint`, `restore`, `listCheckpoints` |
| Coordination | `setupCoordination`, `teardownCoordination` |

## Example

```typescript
import { createForks, teardownForks } from '@tigrisdata/agent-kit';

const { data: forkSet } = await createForks('training-data', 4, {
  prefix: 'sweep-2026-05',
  credentials: { role: 'Editor' },
});

try {
  await Promise.all(
    forkSet.forks.map((fork) => runAgent(fork.bucket, fork.credentials))
  );
} finally {
  await teardownForks(forkSet);
}
```

## Progressive Disclosure

The main `SKILL.md` stays concise. Detailed reference material lives in `resources/`:

- `resources/forks.md` — fork lifecycle, hyperparameter sweep patterns
- `resources/workspaces.md` — TTL behavior, per-user sandboxes
- `resources/checkpoints.md` — branching trajectories, rollback patterns
- `resources/coordination.md` — filter syntax, webhook auth, pipeline patterns

Claude reads these on demand when a user's task touches that area.

## License

MIT
