"""Fills a local UniHub database with test accounts and a little content, so every role can be tried.

1. Start the server (it creates the database file):
       python server.py
2. In a second terminal:
       python demo_setup.py
   Options: --url http://127.0.0.1:8000 (the running server), --db PATH (its database file;
   default: UNIHUB_DB or unihub.db next to server.py).

Accounts are created through the normal API, so they pass the same validation as real sign-ups.
Running the script again is safe: existing accounts are left as they are. All names, e-mails and
passwords here are test values for local use only.
"""
import argparse, http.cookiejar, json, os, sqlite3, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
STUDENT_PW, MODERATOR_PW = "student-pass-2026", "moderator-pass-2026"
ACCOUNTS = [  # login, first, last, password, role, university e-mail marked as confirmed
    ("aliya.student", "Aliya", "Karimova", STUDENT_PW, "student", "aliya.student@astanait.edu.kz"),
    ("daniyar.student", "Daniyar", "Omarov", STUDENT_PW, "student", None),
    ("moderator", "Campus", "Moderator", MODERATOR_PW, "admin", None),
]
ROOMS = [  # the rooms unihub/sensor_sim.py sends readings for
    ("Study room C1.3.270", "Block C1", 8, "pc-c1-3-270"),
    ("Study room C1.2.110", "Block C1", 6, "pc-c1-2-110"),
    ("Group room C2.1.045", "Block C2", 10, "pc-c2-1-045"),
    ("Library quiet zone", "Library", 24, "pc-lib-quiet"),
]


class Client:
    def __init__(self, base):
        self.base = base
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        r = urllib.request.Request(self.base + path, body, method=method,
                                   headers={"Content-Type": "application/json", "Origin": self.base})
        try:
            with self.http.open(r, timeout=15) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


def entry(**extra):
    d = dict(university="AITU", description="", date="2099-12-01", time="16:00", venue="Library", category="Study",
             deadline="2099-12-01", expires="2099-12-01", code="STUDENT", type="Lost", course="Software Engineering",
             year="1st year", format="Offline", smoking="Non-smoker", pets="No pets", lifestyle="Quiet", sleep="Early bird")
    d.update(extra)
    return d


CONTENT = {  # what each new account publishes: (method, path, payload)
    "aliya.student": [
        ("POST", "/api/posts", dict(university="AITU", category="Study",
                                    text="First-year SE student, looking for a Python study partner for the finals.")),
        ("POST", "/api/entries/students", entry(name="Aliya Karimova", subjects="Python, Calculus",
                                                bio="Let's revise Python labs together after classes.")),
    ],
    "daniyar.student": [
        ("POST", "/api/posts", dict(university="AITU", category="Marketplace",
                                    text="Selling ready-made answers for the Calculus II final, 5,000 tenge. DM me.")),
        ("POST", "/api/entries/roommates", entry(name="Daniyar Omarov", budget=110000, district="Yesil",
                                                 bio="Looking for a quiet roommate near campus.")),
        ("POST", "/api/products", dict(university="AITU", name="Graphing calculator", category="Electronics",
                                       price=18000, condition="Like new")),
        ("POST", "/api/entries/events", entry(name="ICT revision session", category="Study",
                                              description="Open revision before the final exam.")),
    ],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--db", default=os.environ.get("UNIHUB_DB", os.path.join(ROOT, "unihub.db")))
    a = ap.parse_args()
    base = a.url.rstrip("/")
    try:
        urllib.request.urlopen(base + "/api/health", timeout=5)
    except OSError:
        sys.exit(f"No UniHub server at {base}. Start it first: python server.py")

    for login, first, last, pw, role, email in ACCOUNTS:
        cl = Client(base)
        code, body = cl.req("POST", "/api/register", dict(first_name=first, last_name=last, birth_date="2006-05-14",
                                                          university="AITU", login=login, password=pw, email=email))
        if code == 409:
            print(f"{login:16} already exists, left unchanged")
            continue
        if code != 201:
            sys.exit(f"{login}: sign-up failed ({code}): {body.get('error')}")
        for method, path, data in CONTENT.get(login, []):
            code, body = cl.req(method, path, data)
            if code not in (200, 201):
                sys.exit(f"{login}: {path} failed ({code}): {body.get('error')}")
        print(f"{login:16} created")

    with sqlite3.connect(a.db) as c:  # what the API cannot do: give a role and mark the university e-mail as confirmed
        for login, *_, role, email in ACCOUNTS:
            c.execute("UPDATE users SET role=? WHERE login=?", (role, login))
            if email:
                c.execute("UPDATE users SET email_verified_at=COALESCE(email_verified_at,?) WHERE login=?",
                          (int(time.time()), login))
        for name, building, seats, dev in ROOMS:
            if not c.execute("SELECT 1 FROM spaces WHERE device_id=?", (dev,)).fetchone():
                c.execute("INSERT INTO spaces(name,building,capacity,device_id) VALUES(?,?,?,?)", (name, building, seats, dev))
    c.close()
    print(f"\nDone. Sign in at {base}/login.html")
    print(f"  student    aliya.student / {STUDENT_PW}   (verified university e-mail)")
    print(f"  student    daniyar.student / {STUDENT_PW}")
    print(f"  moderator  moderator / {MODERATOR_PW}")


if __name__ == "__main__":
    main()
