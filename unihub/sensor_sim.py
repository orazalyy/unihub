"""Simulated study-room door sensors for the "Free study rooms now" card in StudyMate.

It plays the role of the LoRaWAN network server: every few seconds it sends one generated reading per
room to POST /api/iot/readings with the shared device token, exactly as the real webhook would.
Nothing here is real sensor or personal data.

1. Start the server with a device token (any secret string):
       IOT_TOKEN=demo-iot-token python server.py
2. Register the rooms once (demo_setup.py also creates the test accounts):
       python demo_setup.py
3. Send readings until Ctrl+C:
       python sensor_sim.py --token demo-iot-token

Each room follows its own slow wave (full -> busy -> free and back, one cycle every 1-3 minutes) with a
little noise. Study room C1.3.270 starts full and is free about 20 s later, so the "notify me when free"
rule can be shown live in under a minute.
"""
import argparse, json, math, random, sys, time, urllib.error, urllib.request

ROOMS = [  # name, building, seats, device id (the sensor's LoRaWAN DevEUI in a real deployment)
    ("Study room C1.3.270", "Block C1", 8, "pc-c1-3-270"),
    ("Study room C1.2.110", "Block C1", 6, "pc-c1-2-110"),
    ("Group room C2.1.045", "Block C2", 10, "pc-c2-1-045"),
    ("Library quiet zone", "Library", 24, "pc-lib-quiet"),
]
PERIOD = {"pc-c1-3-270": 60, "pc-c1-2-110": 150, "pc-c2-1-045": 110, "pc-lib-quiet": 180}  # seconds per cycle
PHASE = {"pc-c1-3-270": 0, "pc-c1-2-110": 0.5, "pc-c2-1-045": 0.3, "pc-lib-quiet": 0.18}  # share of a cycle at the start


def occupancy(dev, seats, t, rnd):
    wave = 0.5 + 0.55 * math.cos(2 * math.pi * (t / PERIOD[dev] + PHASE[dev]))  # C1.3.270 starts full: the rule fires within a minute
    return max(0, min(seats, round(seats * wave + rnd.uniform(-0.6, 0.6))))


def send(url, token, reading):
    req = urllib.request.Request(url + "/api/iot/readings", json.dumps(reading).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-IoT-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="demo-iot-token")
    ap.add_argument("--interval", type=float, default=3, help="seconds between rounds of readings (default 3)")
    ap.add_argument("--rounds", type=int, default=0, help="stop after N rounds (default: run until Ctrl+C)")
    a = ap.parse_args()
    rnd, start, n = random.Random(9), time.time(), 0
    battery = {dev: rnd.randint(78, 100) for *_, dev in ROOMS}
    while not a.rounds or n < a.rounds:
        t = time.time() - start
        for name, _, seats, dev in ROOMS:
            occ = occupancy(dev, seats, t, rnd)
            code, body = send(a.url, a.token, {"device_id": dev, "occupancy": occ, "battery": battery[dev]})
            extra = f", notified {body['notified']}" if body.get("notified") else ""
            print(f"{time.strftime('%H:%M:%S')}  {dev:13} {occ:2}/{seats:<2} -> {code} {body.get('status', body.get('error'))}{extra}")
            if code in (401, 403, 404):
                sys.exit("Rejected: check --token, IOT_TOKEN on the server and that demo_setup.py was run on its database.")
        n += 1
        time.sleep(a.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
