# bazaar-contrib-server-database

The server's own database, beside the node's. The `server-database` entry opens the storage it selects in private bindings, by default the generic sqlite at `~/.bcn/bcs.sqlite3`, and offers it as `SERVER_DB` and `SERVER_SCHEMA`; the node keeps `DB` and `SCHEMA`, and either can use another backend.

```toml
[[contribs]]
package = "bazaar-contrib-server-database~=0.3.0rc1"
[[contribs.enabled]]
entry = "server-database"
[contribs.enabled.config]
storage = "sqlite"
```

A module that uses the server's database accepts `SERVER_DB` or `SERVER_SCHEMA`.
