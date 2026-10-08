# Database migrations

Numbered SQL files, applied in order. Each file is applied once and never edited
afterwards; any further change is a new file with the next number. Do not wrap a
file in BEGIN/COMMIT: the runner applies each file in one transaction
(`psql -1 -f <file>`, or Supabase's migration tools).

| File | What it does | Applied to Supabase |
|---|---|---|
| `001_baseline.sql` | The live schema as of 7 Oct 2026 (replaces `db/schema/schema.sql`) | 7 Oct 2026 (no-op; recorded in history) |
| `002_revoke_public_api_privileges.sql` | Removes Data API privileges from `anon` / `authenticated`, now and for new objects (audit A5) | 7 Oct 2026 |
| `003_mark_regime_output_placeholder.sql` | Tags the Phase 2 regime rows `HMM_v1-placeholder` (audit A2) | 7 Oct 2026 |

Supabase keeps its own history (Dashboard → Database → Migrations); the names there
match these file names. Check it before applying anything:

```sql
SELECT version, name FROM supabase_migrations.schema_migrations ORDER BY version;
```

Tables for the Phase 3 model (probabilities, model registry, pipeline runs) will
arrive as `004_…` in the same pull request as the code that writes them, so the
schema and the code never drift apart again.
