# Run the reference-linking playground

From the repository root:

```bash
uv run python packages/linking/examples/client/server.py
```

Open **http://127.0.0.1:8787**.

1. Click **Select the example passages**.
2. Click **Preview selections**, then **Save link**.
3. Click **Open destination**.
4. Try **Approve link** as Reader: expect a permission error.
5. Choose Reviewer and approve: expect approved review, draft publication.
6. Click **Test stale selection**: expect a rejected changed version.

The JavaScript helper is the code from the [client guide](../../../../specs/reference-linking/client/README.md).
This local fixture server uses the real Python models, snapshot resolver and SQLite
revision history. It binds only to loopback and uses synthetic demo roles. It is
not production JWT authentication or a PostgreSQL authorization test. Documents
are sample text and links live in a temporary database cleared on restart.
Stop the server with Ctrl+C. No live Supabase or external publication is involved.
