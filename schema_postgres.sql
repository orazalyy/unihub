-- Postgres schema for the Vercel deployment. One-to-one translation of the
-- SQLite schema in unihub/server.py + unihub/features.py, already folded
-- flat (no incremental ALTER TABLE migrations needed: this database starts
-- empty every time). Applied once by app.py on cold start.
--
-- citext gives the `login` column the same case-insensitive comparison that
-- SQLite's `COLLATE NOCASE` gave it, with zero changes needed to any query.
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS users(
  id SERIAL PRIMARY KEY,
  first_name TEXT NOT NULL, last_name TEXT NOT NULL, birth_date TEXT NOT NULL,
  university TEXT NOT NULL, login CITEXT NOT NULL UNIQUE, email TEXT,
  pw_salt BYTEA NOT NULL, pw_hash BYTEA NOT NULL, created_at BIGINT NOT NULL,
  bio TEXT NOT NULL DEFAULT '', interests TEXT NOT NULL DEFAULT '', community TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts(
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL, university TEXT NOT NULL, category TEXT NOT NULL,
  text TEXT NOT NULL, likes INTEGER NOT NULL DEFAULT 0, comments INTEGER NOT NULL DEFAULT 0,
  followed INTEGER NOT NULL DEFAULT 0, tone TEXT NOT NULL DEFAULT 'blue',
  time_label TEXT, sort_key BIGINT NOT NULL, is_mine INTEGER NOT NULL DEFAULT 0,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS products(
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL, category TEXT NOT NULL, price INTEGER NOT NULL,
  seller TEXT NOT NULL, university TEXT NOT NULL, condition TEXT NOT NULL,
  photo INTEGER NOT NULL DEFAULT 0, is_mine INTEGER NOT NULL DEFAULT 0,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  image TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Available'
);
CREATE TABLE IF NOT EXISTS students(
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL, university TEXT NOT NULL, course TEXT NOT NULL, year TEXT NOT NULL,
  subjects TEXT NOT NULL, format TEXT NOT NULL, bio TEXT NOT NULL, tone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roommates(
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL, university TEXT NOT NULL, budget INTEGER NOT NULL, district TEXT NOT NULL,
  smoking TEXT NOT NULL, pets TEXT NOT NULL, lifestyle TEXT NOT NULL, sleep TEXT NOT NULL,
  bio TEXT NOT NULL, tone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries(
  id SERIAL PRIMARY KEY, kind TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  university TEXT NOT NULL, payload TEXT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS reactions(
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
  PRIMARY KEY(user_id,post_id)
);
CREATE TABLE IF NOT EXISTS comments(
  id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
  text TEXT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS follows(
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, target_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY(user_id,target_id), CHECK(user_id!=target_id)
);
CREATE TABLE IF NOT EXISTS responses(
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE,
  status TEXT NOT NULL, PRIMARY KEY(user_id,entry_id)
);
CREATE TABLE IF NOT EXISTS messages(
  id SERIAL PRIMARY KEY, sender_id INTEGER REFERENCES users(id) ON DELETE CASCADE, recipient_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  text TEXT NOT NULL, created_at BIGINT NOT NULL, read_at BIGINT, CHECK(sender_id!=recipient_id)
);
CREATE TABLE IF NOT EXISTS notifications(
  id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, text TEXT NOT NULL, href TEXT NOT NULL,
  created_at BIGINT NOT NULL, read_at BIGINT
);
-- Added for Project Stage 2 (R1 email verification, R7 moderation). ALTER ... IF NOT
-- EXISTS upgrades the live database in place; on an empty one it is a no-op.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'student';
CREATE TABLE IF NOT EXISTS email_codes(
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, email TEXT NOT NULL,
  code_hash TEXT NOT NULL, expires_at BIGINT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  sent_at BIGINT NOT NULL, window_start BIGINT NOT NULL, sends INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reports(
  id SERIAL PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, reason TEXT NOT NULL,
  created_at BIGINT NOT NULL, UNIQUE(post_id,user_id)
);
CREATE TABLE IF NOT EXISTS moderation_log(
  id SERIAL PRIMARY KEY, admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL, action TEXT NOT NULL,
  target_kind TEXT NOT NULL, target_id INTEGER NOT NULL, author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  excerpt TEXT NOT NULL, reason TEXT NOT NULL, created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_recipient ON messages(recipient_id,id);
CREATE INDEX IF NOT EXISTS entries_kind ON entries(kind,university);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id,id);
-- D3: study-room occupancy sensors
CREATE TABLE IF NOT EXISTS spaces(
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, building TEXT NOT NULL,
  capacity INTEGER NOT NULL CHECK(capacity>0), device_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS space_readings(
  id SERIAL PRIMARY KEY, space_id INTEGER NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
  occupancy INTEGER NOT NULL, battery INTEGER NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS space_watches(
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  space_id INTEGER NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
  created_at BIGINT NOT NULL, PRIMARY KEY(user_id,space_id)
);
CREATE INDEX IF NOT EXISTS space_readings_time ON space_readings(space_id,created_at);
-- failed log-ins of the last 5 minutes, shared by all serverless instances
CREATE TABLE IF NOT EXISTS login_failures(login TEXT NOT NULL, ip TEXT NOT NULL, at BIGINT NOT NULL);
CREATE INDEX IF NOT EXISTS login_failures_key ON login_failures(login,ip);
