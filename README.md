# UniHub

UniHub is a web platform for university students in Kazakhstan. It gathers what is usually spread over
many chats and groups into one place per university: campus news, study partners, roommates, a
second-hand marketplace, events, lost & found, opportunities, student discounts and private messages.
Moderators keep the community safe by reviewing reported posts.

- **Live site:** https://unihubb.vercel.app
- **Team:** Shatyrkhan Orazali, Saltay Nuradil (SE2621, Astana IT University)

## User roles

| Role | What they can do |
|---|---|
| Student | Sign up, confirm a university e-mail (✓ badge), post and filter the feed, like and comment, find study partners and roommates, sell items, join events, message other students, report a post, get notified when a study room becomes free |
| Moderator (`role = admin`) | Everything a student can, plus the **Moderation** page: report queue, remove or keep a post or listing with a reason, moderation log, community statistics |

## Run it locally (about 2 minutes)

You only need **Python 3.10 or newer**. The local server uses the standard library and SQLite, so
there is nothing to install.

```bash
git clone https://github.com/orazalyy/unihub.git
cd unihub/unihub
python server.py
```

Open http://127.0.0.1:8000. The database file `unihub/unihub.db` is created on the first start.

To create the **test accounts**, leave the server running and run this in a second terminal (from the
same `unihub/unihub` folder):

```bash
python demo_setup.py
```

On Windows you can also double-click `unihub/start.bat`, which starts the server and opens the browser.

### Test accounts

Created by `demo_setup.py` in your local database. They are test values for local use only.

| Role | Login | Password | Notes |
|---|---|---|---|
| Student | `aliya.student` | `student-pass-2026` | Confirmed university e-mail, so the ✓ badge is shown; has a StudyMate profile (Python) |
| Student | `daniyar.student` | `student-pass-2026` | Has a CoLiving listing (Yesil, 110 000 ₸), a marketplace item, an event, and a post that breaks campus rules, so it can be reported |
| Moderator | `moderator` | `moderator-pass-2026` | Opens **Moderation** in the sidebar (`/admin.html`); a student who opens that page gets HTTP 403 |

On the **live site** you can sign up as a student yourself in about a minute. Moderator access on the
live site is not published here, because real students use it; the team can show it on request.

### Try the main journeys

1. **Student:** sign in as `aliya.student` → UniFeed → write a post → StudyMate → filter by subject →
   message a study partner.
2. **Moderator:** in a private window sign in as `aliya.student` and press **Report** under Daniyar's post.
   Then sign in as `moderator` → Moderation → remove the post with a reason. Daniyar gets a notification
   with the reason and the action is written to the moderation log.
3. **E-mail confirmation:** Settings → Email verification → Send code. Without SMTP settings the local
   server prints the 6-digit code to its console instead of sending an e-mail.

### Study-room sensors (IoT simulation)

StudyMate shows a **Free study rooms now** card fed by people-counting sensors. The sensors are
simulated: `sensor_sim.py` sends readings to the same webhook a real sensor network would call.

```bash
IOT_TOKEN=demo-iot-token python server.py          # terminal 1 (PowerShell: $env:IOT_TOKEN="demo-iot-token"; python server.py)
python demo_setup.py                               # terminal 2, once: accounts and the four rooms
python sensor_sim.py --token demo-iot-token        # terminal 2, until Ctrl+C
```

Press **Notify me when free** on a full room. When it drops to half its seats or fewer, you get a
notification. Without `IOT_TOKEN` the webhook answers 404.

### Run the tests

```bash
cd unihub
python test_integration.py
```

15 integration tests start their own server on a random port with a temporary database, so your data
is not touched. They cover accounts, privacy, ownership rules, every section, photos, e-mail
confirmation, reports and moderation, the sensor webhook and the login limit.

## How it is built

```
Browser (desktop / phone, 360 px+)
   │ HTTPS only (HTTP → 308, HSTS)
   ▼
Vercel ── CDN: static pages from public/
       └─ Python function: app.py (Flask) + vercel_features.py
                │ TLS (sslmode=require)
                ▼
          Neon PostgreSQL (users, posts, listings, messages, product photos, sensor readings)
Simulated sensors ── POST /api/iot/readings with X-IoT-Token ──▶ same API
```

There are two backends with the same API and the same front end (`unihub/site/`):

| | Local / Render | Live site (Vercel) |
|---|---|---|
| Server | `unihub/server.py` (Python standard library) | `app.py` (Flask) |
| Features | `unihub/features.py` | `vercel_features.py` (same logic) |
| Database | SQLite file `unihub/unihub.db` | PostgreSQL on Neon via `dbshim.py`, schema `schema_postgres.sql` |
| Static files | served from `unihub/site/` | copied to `public/` by `build_static.py` |

### Repository layout

| Path | What it is |
|---|---|
| `unihub/site/` | Front end: HTML pages, `app.js`, `styles.css` |
| `unihub/server.py` | HTTP server, accounts, sessions, posts and products, schema |
| `unihub/features.py` | All other sections, messages, notifications, e-mail codes, reports and moderation, sensors, login limit |
| `unihub/test_integration.py` | Integration tests |
| `unihub/demo_setup.py`, `unihub/sensor_sim.py` | Test accounts and the sensor simulation |
| `unihub/backup.py` | Consistent copy of the SQLite database into `backups/` |
| `app.py`, `vercel_features.py`, `dbshim.py`, `schema_postgres.sql` | The Vercel + PostgreSQL version |
| `build_static.py` | Copies `unihub/site/` to `public/` (run it after every front-end change) |
| `.github/workflows/uptime.yml` | Checks `/api/health` on the live site on a schedule |

## Security

- Passwords: scrypt with a random 16-byte salt per user; only the 32-byte hash is stored.
- Sessions: random token in an HttpOnly, SameSite=Lax cookie (Secure on the live site); only its
  SHA-256 hash is in the database. Changing the password ends all sessions.
- Login limit: 5 failed attempts per login and IP in 5 minutes, kept in the database so it holds
  across all server instances. A wrong login and a wrong password get the same answer.
- Access rules are checked on the server: users edit and delete only their own records; moderator
  routes check `role = 'admin'`; requests from another site's `Origin` are refused.
- E-mail codes are stored only as hashes, expire after 10 minutes and allow 5 attempts.
- Private data (e-mail, date of birth) is never sent to other users; messages are visible only to the
  sender and the receiver.

## Deploy your own copy on Vercel

1. Create a free PostgreSQL database on [Neon](https://neon.tech) and copy the **pooled** connection string.
2. Check it: `DATABASE_URL="postgresql://..." python verify_postgres.py` (five steps print `OK`).
3. Import the repository on [vercel.com/new](https://vercel.com/new) and set the environment variables:

| Variable | Required | Meaning |
|---|---|---|
| `DATABASE_URL` | yes | Neon pooled connection string |
| `ADMIN_LOGINS` | no | Comma-separated logins that get the moderator role on start |
| `SMTP_USER`, `SMTP_PASSWORD` | no | Mailbox that sends e-mail codes; without them the Verify button is hidden. Optional: `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM` |
| `IOT_TOKEN` | no | Shared secret for the sensor webhook; without it the webhook is off |

4. Open `https://<project>.vercel.app/api/health`: it should answer `{"app": "UniHub", ...}`.

More detail (in Russian) is in [README-VERCEL.md](README-VERCEL.md).

The local server reads `PORT` (default 8000), `HOST` (default 127.0.0.1), `UNIHUB_DB` (database
file), `ADMIN_LOGINS` and `IOT_TOKEN` in the same way.
