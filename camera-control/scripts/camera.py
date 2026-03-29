#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "requests",
# ]
# ///
"""
Camera control CLI for SSAU IP camera (hi3510 CGI API).
Reads config from camera_config.ini (in the same directory alongside this script).

Exit codes:
  0 — success
  1 — camera/network error
  2 — bad arguments
"""

import argparse
import configparser
import json
import sys
import time
from pathlib import Path

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    print(json.dumps({"ok": False, "error": "requests not installed. Run: pip install requests"}))
    sys.exit(1)

CONFIG_PATH = Path(__file__).parent / "camera_config.ini"


def load_config():
    cfg = configparser.ConfigParser()
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
    cfg.read(CONFIG_PATH)
    return cfg["camera"]


def load_panorama_config():
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH)
    sec = cfg["panorama"] if "panorama" in cfg else {}
    return {
        "ptz_sweep_secs": float(sec.get("ptz_sweep_secs", 8)),
        "ptz_settle_secs": float(sec.get("ptz_settle_secs", 2)),
        "home_settle_secs": float(sec.get("home_settle_secs", 30)),
    }


class Camera:
    def __init__(self):
        c = load_config()
        self.ip = c["ip"]
        self.port = c.getint("port", fallback=80)
        self.username = c["username"]
        self.password = c["password"]
        self.base = f"http://{self.ip}:{self.port}"
        self.auth = HTTPBasicAuth(self.username, self.password)
        self.timeout = 5

    def _get(self, path, params=None):
        url = f"{self.base}{path}"
        r = requests.get(url, params=params, auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        return r.text.strip()

    def _cgi(self, cmd, **kwargs):
        params = {"cmd": cmd}
        for k, v in kwargs.items():
            params[f"-{k}"] = v
        return self._get("/cgi-bin/hi3510/param.cgi", params=params)

    def get_server_info(self):
        return self._cgi("getserverinfo")

    def get_video_attr(self):
        return self._cgi("getvideoattr")

    def get_venc_attr(self, channel=11):
        return self._cgi("getvencattr", chn=channel)

    def get_image_attr(self):
        return self._cgi("getimageattr")

    def set_image_attr(self, **kwargs):
        return self._cgi("setimageattr", **kwargs)

    def get_infrared(self):
        return self._cgi("getinfrared")

    def set_infrared(self, status):
        return self._cgi("setinfrared", infraredstat=status)

    def ptz_ctrl(self, act, speed=45, step=0):
        return self._cgi("ptzctrl", step=step, act=act, speed=speed)

    def preset(self, act, number, status=1):
        if act == "set":
            return self._cgi("preset", act=act, status=status, number=number)
        return self._cgi("preset", act=act, number=number)

    def snapshot(self):
        url = f"{self.base}/web/tmpfs/snap.jpg"
        r = requests.get(url, auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        return r.content

    def alarm_head(self):
        """HEAD request on alarmsnap.jpg, returns (etag, last_modified, content_length)."""
        url = f"{self.base}/web/tmpfs/alarmsnap.jpg"
        r = requests.head(url, auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        return (
            r.headers.get("Etag", "").strip('"'),
            r.headers.get("Last-Modified", ""),
            int(r.headers.get("Content-Length", 0)),
        )

    def alarm_snapshot(self):
        """Download alarmsnap.jpg bytes."""
        url = f"{self.base}/web/tmpfs/alarmsnap.jpg"
        r = requests.get(url, auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        return r.content


def ok(result):
    print(json.dumps({"ok": True, "result": result}), flush=True)


def err(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}), flush=True)
    sys.exit(code)


# State file: persists last seen ETag across calls
STATE_FILE = Path(__file__).parent / ".alarm_state.json"


def _load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def parse_cgi_response(text):
    """Parse var key="val"; lines into a dict."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("var ") and "=" in line:
            key, _, val = line[4:].partition("=")
            result[key.strip()] = val.strip().strip(";").strip('"')
    return result if result else text


def _cmd_check(cam):
    """Run all health checks, collect results regardless of individual failures."""
    checks = {}
    failed = []

    def step(name, fn):
        try:
            result = fn()
            if isinstance(result, dict):
                checks[name] = {"ok": True, **result}
            else:
                checks[name] = {"ok": True}
        except Exception as e:
            checks[name] = {"ok": False, "error": str(e)}
            failed.append(name)

    # 1. connectivity + server info
    def check_info():
        parsed = parse_cgi_response(cam.get_server_info())
        return parsed if isinstance(parsed, dict) else {}
    step("info", check_info)

    # 2-5. PTZ four directions (brief 1s movement each)
    PTZ_CHECK_SECS = 1.0
    for direction in ["left", "right", "up", "down"]:
        def check_ptz(d=direction):
            cam.ptz_ctrl(d)
            time.sleep(PTZ_CHECK_SECS)
            cam.ptz_ctrl("stop")
            return {}
        step(f"ptz_{direction}", check_ptz)

    # 6. PTZ home
    def check_ptz_home():
        cam.ptz_ctrl("home")
        return {}
    step("ptz_home", check_ptz_home)

    # 7. snapshot (verify image retrieval)
    def check_snapshot():
        data = cam.snapshot()
        return {"size_bytes": len(data)}
    step("snapshot", check_snapshot)

    # 8. image settings read
    def check_image():
        parse_cgi_response(cam.get_image_attr())
        return {}
    step("image", check_image)

    # 9. infrared status read
    def check_infrared():
        parse_cgi_response(cam.get_infrared())
        return {}
    step("infrared", check_infrared)

    # 10. alarm endpoint reachability
    def check_alarm():
        etag, last_modified, size = cam.alarm_head()
        return {"etag": etag, "size_bytes": size}
    step("alarm", check_alarm)

    return {
        "overall": "fail" if failed else "pass",
        "failed": failed,
        "checks": checks,
    }


def _cmd_panorama(cam, output_dir, pcfg):
    """Sweep camera to 4 positions and capture a photo at each."""
    sweep = pcfg["ptz_sweep_secs"]
    settle = pcfg["ptz_settle_secs"]
    home_settle = pcfg["home_settle_secs"]

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    photos = {}

    def snap(name):
        data = cam.snapshot()
        path = out / f"{name}.jpg"
        path.write_bytes(data)
        photos[name] = str(path.resolve())

    # Left end
    cam.ptz_ctrl("left")
    time.sleep(sweep)
    cam.ptz_ctrl("stop")
    time.sleep(settle)
    snap("left")

    # Right end (from left end, sweep * 2 to cross full range)
    cam.ptz_ctrl("right")
    time.sleep(sweep * 2)
    cam.ptz_ctrl("stop")
    time.sleep(settle)
    snap("right")

    # Home position
    cam.ptz_ctrl("home")
    time.sleep(home_settle)
    snap("home")

    # Up end
    cam.ptz_ctrl("up")
    time.sleep(sweep)
    cam.ptz_ctrl("stop")
    time.sleep(settle)
    snap("up")

    # Return to home
    cam.ptz_ctrl("home")
    time.sleep(home_settle)

    return {"photos": photos, "config": pcfg}


def main():
    parser = argparse.ArgumentParser(
        description="SSAU IP Camera control CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  camera.py info
  camera.py ptz --act left --speed 30
  camera.py ptz --act stop
  camera.py preset --act set --number 1
  camera.py preset --act goto --number 1
  camera.py snapshot --output /tmp/snap.jpg
  camera.py image --get
  camera.py image --brightness 60 --flip on --mirror off
  camera.py infrared --status auto
  camera.py video --get
  camera.py venc --channel 11
""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # info
    sub.add_parser("info", help="Camera model, firmware, SD card status")

    # ptz
    p = sub.add_parser("ptz", help="PTZ movement and zoom")
    p.add_argument(
        "--act", required=True,
        choices=["up", "down", "left", "right", "home", "stop",
                 "zoomin", "zoomout", "focusin", "focusout",
                 "hscan", "vscan"],
        help="PTZ action",
    )
    p.add_argument("--speed", type=int, default=45, metavar="1-63", help="Speed (default: 45)")
    p.add_argument("--step", type=int, default=0, choices=[0, 1], help="0=continuous, 1=step")

    # preset
    p = sub.add_parser("preset", help="Save or go to a preset position")
    p.add_argument("--act", required=True, choices=["set", "goto"], help="Action")
    p.add_argument("--number", required=True, type=int, help="Preset number")

    # snapshot
    p = sub.add_parser("snapshot", help="Capture a JPEG snapshot")
    p.add_argument("--output", default="snapshot.jpg", help="Output file path (default: snapshot.jpg)")

    # image
    p = sub.add_parser("image", help="Get or set image parameters")
    p.add_argument("--get", action="store_true", help="Read current image settings")
    p.add_argument("--brightness", type=int, metavar="0-100")
    p.add_argument("--contrast", type=int, metavar="0-100")
    p.add_argument("--saturation", type=int, metavar="0-100")
    p.add_argument("--sharpness", type=int, metavar="0-100")
    p.add_argument("--hue", type=int, metavar="0-100")
    p.add_argument("--flip", choices=["on", "off"])
    p.add_argument("--mirror", choices=["on", "off"])
    p.add_argument("--noise", type=int, metavar="0-100")
    p.add_argument("--aemode", type=int, metavar="0-22")
    p.add_argument("--imgmode", type=int, choices=[0, 1])

    # infrared
    p = sub.add_parser("infrared", help="IR cut control")
    p.add_argument("--get", action="store_true", help="Read current IR status")
    p.add_argument("--status", choices=["auto", "open", "close"])

    # video
    p = sub.add_parser("video", help="Get video mode (resolution)")
    p.add_argument("--get", action="store_true", help="Read video attr")

    # venc
    p = sub.add_parser("venc", help="Get encoding params for a stream channel")
    p.add_argument("--channel", type=int, choices=[11, 12, 13], default=11,
                   help="11=main, 12=sub, 13=mobile (default: 11)")

    # alarm (one-shot active query)
    p = sub.add_parser("alarm", help="One-shot: check if a new motion alarm has fired since last call")
    p.add_argument("--output-dir", default=".", metavar="DIR",
                   help="Directory to save alarm snapshot when triggered (default: .)")
    p.add_argument("--save", action="store_true",
                   help="Save alarm snapshot to --output-dir when triggered")
    p.add_argument("--reset", action="store_true",
                   help="Reset stored ETag state (treat next call as first)")

    # watch (background polling loop)
    p = sub.add_parser("watch", help="Background polling: emit JSON events to stdout on each new alarm")
    p.add_argument("--interval", type=float, default=2.0, metavar="SEC",
                   help="Poll interval in seconds (default: 2)")
    p.add_argument("--output-dir", default=".", metavar="DIR",
                   help="Directory to save alarm snapshots")
    p.add_argument("--no-save", action="store_true",
                   help="Do not save snapshots, only emit JSON events")

    # check
    sub.add_parser("check", help="Run a full health check of all camera functions and return a report")

    # panorama
    p = sub.add_parser("panorama", help="Sweep camera to 4 positions and capture a photo at each")
    p.add_argument("--output-dir", default=".", metavar="DIR",
                   help="Directory to save panorama photos (default: .)")

    args = parser.parse_args()

    try:
        cam = Camera()
    except FileNotFoundError as e:
        err(str(e))
    except Exception as e:
        err(f"Config error: {e}")

    try:
        if args.cmd == "info":
            raw = cam.get_server_info()
            ok(parse_cgi_response(raw))

        elif args.cmd == "ptz":
            if not (1 <= args.speed <= 63):
                err("--speed must be between 1 and 63", code=2)
            raw = cam.ptz_ctrl(args.act, speed=args.speed, step=args.step)
            ok({"action": args.act, "speed": args.speed, "response": raw})

        elif args.cmd == "preset":
            raw = cam.preset(args.act, args.number)
            ok({"action": args.act, "number": args.number, "response": raw})

        elif args.cmd == "snapshot":
            data = cam.snapshot()
            out = Path(args.output)
            out.write_bytes(data)
            ok({"path": str(out.resolve()), "size_bytes": len(data)})

        elif args.cmd == "image":
            if args.get:
                ok(parse_cgi_response(cam.get_image_attr()))
            else:
                kwargs = {}
                for field in ["brightness", "contrast", "saturation", "sharpness",
                              "hue", "flip", "mirror", "noise", "aemode", "imgmode"]:
                    v = getattr(args, field)
                    if v is not None:
                        kwargs[field] = v
                if not kwargs:
                    err("No image parameters specified. Use --get to read, or pass params to set.", code=2)
                raw = cam.set_image_attr(**kwargs)
                ok({"set": kwargs, "response": raw})

        elif args.cmd == "infrared":
            if args.get or not args.status:
                ok(parse_cgi_response(cam.get_infrared()))
            else:
                raw = cam.set_infrared(args.status)
                ok({"status": args.status, "response": raw})

        elif args.cmd == "video":
            ok(parse_cgi_response(cam.get_video_attr()))

        elif args.cmd == "venc":
            ok(parse_cgi_response(cam.get_venc_attr(args.channel)))

        elif args.cmd == "alarm":
            if args.reset:
                _save_state({})
                ok({"reset": True})
                return

            etag, last_modified, size = cam.alarm_head()
            state = _load_state()
            prev_etag = state.get("etag")

            if prev_etag is None:
                # First call: record baseline, no alarm reported
                _save_state({"etag": etag, "last_modified": last_modified})
                ok({"triggered": False, "note": "baseline recorded", "etag": etag})
            elif etag == prev_etag:
                ok({"triggered": False, "etag": etag, "last_modified": last_modified})
            else:
                # New alarm
                result = {
                    "triggered": True,
                    "etag": etag,
                    "last_modified": last_modified,
                    "size_bytes": size,
                }
                if args.save:
                    out_dir = Path(args.output_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    # Derive timestamp from ETag hex prefix (unix timestamp)
                    try:
                        ts = int(etag.split(".")[0], 16)
                        from datetime import datetime, timezone
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        fname = f"alarm_{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
                    except Exception:
                        fname = f"alarm_{etag}.jpg"
                    path = out_dir / fname
                    path.write_bytes(cam.alarm_snapshot())
                    result["saved_to"] = str(path.resolve())
                _save_state({"etag": etag, "last_modified": last_modified})
                ok(result)

        elif args.cmd == "watch":
            import signal
            import time as _time

            out_dir = Path(args.output_dir)
            if not args.no_save:
                out_dir.mkdir(parents=True, exist_ok=True)

            # Graceful shutdown on SIGINT/SIGTERM
            _running = [True]
            def _stop(sig, frame):
                _running[0] = False
            signal.signal(signal.SIGINT, _stop)
            signal.signal(signal.SIGTERM, _stop)

            prev_etag = None
            print(json.dumps({"ok": True, "event": "started",
                               "interval": args.interval}), flush=True)

            while _running[0]:
                try:
                    etag, last_modified, size = cam.alarm_head()
                    if prev_etag is None:
                        prev_etag = etag  # baseline
                    elif etag != prev_etag:
                        event = {
                            "ok": True,
                            "event": "alarm",
                            "etag": etag,
                            "last_modified": last_modified,
                            "size_bytes": size,
                        }
                        if not args.no_save:
                            try:
                                ts = int(etag.split(".")[0], 16)
                                from datetime import datetime, timezone
                                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                                fname = f"alarm_{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
                            except Exception:
                                fname = f"alarm_{etag}.jpg"
                            path = out_dir / fname
                            path.write_bytes(cam.alarm_snapshot())
                            event["saved_to"] = str(path.resolve())
                        prev_etag = etag
                        print(json.dumps(event), flush=True)
                except requests.exceptions.RequestException as e:
                    print(json.dumps({"ok": False, "event": "error", "error": str(e)}),
                          flush=True)

                _time.sleep(args.interval)

            print(json.dumps({"ok": True, "event": "stopped"}), flush=True)

        elif args.cmd == "check":
            ok(_cmd_check(cam))

        elif args.cmd == "panorama":
            pcfg = load_panorama_config()
            ok(_cmd_panorama(cam, args.output_dir, pcfg))

    except requests.exceptions.ConnectionError:
        err(f"Cannot connect to camera at {cam.base}")
    except requests.exceptions.Timeout:
        err(f"Connection timed out to {cam.base}")
    except requests.exceptions.HTTPError as e:
        err(f"HTTP error: {e}")
    except Exception as e:
        err(str(e))


if __name__ == "__main__":
    main()
