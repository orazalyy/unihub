# UniHub — local server

This folder is the self-contained version of UniHub: Python standard library + SQLite, no packages to
install. The same front end (`site/`) also runs on Vercel with PostgreSQL (see the repository root).

```bash
python server.py          # http://127.0.0.1:8000, creates unihub.db
python demo_setup.py      # second terminal: test accounts for every role
python test_integration.py
```

Setup, test accounts, the sensor simulation, architecture and security are described in the
[main README](../README.md).

## Files

- `server.py` — HTTP server, accounts, sessions, posts and products, database schema and migrations.
- `features.py` — the other sections, messages, notifications, e-mail codes, reports and moderation,
  study-room sensors, login limit.
- `site/` — HTML pages, `app.js`, `styles.css`.
- `demo_setup.py` — test accounts and sample content; `sensor_sim.py` — simulated room sensors.
- `test_integration.py` — 15 integration tests on a temporary database.
- `backup.py` — consistent copy of `unihub.db` into `backups/`.
- `launcher.py`, `start.bat` — double-click start on Windows.

`unihub.db` keeps all data between restarts, including product photos. Do not delete it if you want to
keep accounts and posts; run `python backup.py` for a copy.
