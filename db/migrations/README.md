# Database migrations

Numbered SQL files, applied in order. Each file is applied once and never edited
afterwards; any further change is a new file with the next number.

| File | What it does | Applied to Supabase? |
|---|---|---|
| `001_baseline.sql` | The live schema as of 7 Oct 2026 (replaces `db/schema/schema.sql`) | Matches the live DB (no-op there) |
| `002_revoke_public_api_privileges.sql` | Removes Data API privileges from `anon` / `authenticated` (audit A5) | **No — waiting for team approval** |

Tables for the Phase 3 model (probabilities, model registry, pipeline runs) will
arrive as `003_…` in the same pull request as the code that writes them, so the
schema and the code never drift apart again.
