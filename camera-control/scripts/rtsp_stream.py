#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "requests",
#   "opencv-python-headless",
# ]
# ///
"""
RTSP stream receiver for SSAU hi3510 IP camera.

Stream URLs (default port 554):
  rtsp://<ip>:554/11  — main stream  (channel 11)
  rtsp://<ip>:554/12  — sub stream   (channel 12)
  rtsp://<ip>:554/13  — mobile stream (channel 13)

RTSP auth can be embedded: rtsp://user:pass@<ip>:554/11
or disabled on camera with: param.cgi?cmd=setrtspauth&-rtsp_aenable=0

Usage:
  python rtsp_stream.py --help
  python rtsp_stream.py url                   # print RTSP URL and exit
  python rtsp_stream.py capture               # save one frame as JPEG
  python rtsp_stream.py record --duration 10  # record 10s MP4
  python rtsp_stream.py display               # show live window (requires display)

Exit codes:
  0 — success
  1 — stream/network error
  2 — bad arguments
"""

import argparse
import configparser
import json
import sys
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "camera_config.ini"
DEFAULT_RTSP_PORT = 554


def load_config():
    cfg = configparser.ConfigParser()
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
    cfg.read(CONFIG_PATH)
    return cfg["camera"]


def build_rtsp_url(c, channel: int, with_auth: bool = True) -> str:
    ip = c["ip"]
    port = c.getint("rtsp_port", fallback=DEFAULT_RTSP_PORT)
    if with_auth:
        user = c["username"]
        passwd = c["password"]
        return f"rtsp://{user}:{passwd}@{ip}:{port}/{channel}"
    return f"rtsp://{ip}:{port}/{channel}"


def ok(result):
    print(json.dumps({"ok": True, "result": result}), flush=True)


def err(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}), flush=True)
    sys.exit(code)


def _open_stream(url: str):
    try:
        import cv2
    except ImportError:
        err("opencv-python-headless not installed. Run: pip install opencv-python-headless")

    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        err(f"Cannot open RTSP stream: {url}")
    return cap


def cmd_url(c, channel: int, no_auth: bool):
    url = build_rtsp_url(c, channel, with_auth=not no_auth)
    ok({"url": url, "channel": channel})


def cmd_capture(c, channel: int, output: str):
    import cv2

    url = build_rtsp_url(c, channel)
    cap = _open_stream(url)
    try:
        ret, frame = cap.read()
        if not ret:
            err("Failed to read frame from stream")
        out = Path(output)
        cv2.imwrite(str(out), frame)
        h, w = frame.shape[:2]
        ok({"path": str(out.resolve()), "width": w, "height": h})
    finally:
        cap.release()


def cmd_record(c, channel: int, output: str, duration: float, fps_limit: float):
    import cv2

    url = build_rtsp_url(c, channel)
    cap = _open_stream(url)
    try:
        # Probe stream FPS and resolution
        native_fps = cap.get(cv2.CAP_PROP_FPS)
        if native_fps <= 0 or native_fps > 120:
            native_fps = fps_limit  # fallback if camera reports 0

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        out_path = Path(output)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out_path), fourcc, min(native_fps, fps_limit),
                                 (width, height))
        if not writer.isOpened():
            err(f"Cannot open output file for writing: {out_path}")

        start = time.monotonic()
        frames = 0
        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= duration:
                    break
                ret, frame = cap.read()
                if not ret:
                    break
                writer.write(frame)
                frames += 1
        finally:
            writer.release()

        ok({
            "path": str(out_path.resolve()),
            "frames": frames,
            "duration_secs": round(time.monotonic() - start, 2),
            "resolution": f"{width}x{height}",
            "fps": round(native_fps, 1),
        })
    finally:
        cap.release()


def cmd_display(c, channel: int):
    import cv2

    url = build_rtsp_url(c, channel)
    cap = _open_stream(url)
    print(json.dumps({"ok": True, "event": "started", "url": build_rtsp_url(c, channel, with_auth=False)}),
          flush=True)
    print("Press 'q' to quit.", file=sys.stderr)
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            cv2.imshow("RTSP Stream", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    ok({"event": "stopped"})


def main():
    parser = argparse.ArgumentParser(
        description="RTSP stream receiver for SSAU hi3510 IP camera",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  rtsp_stream.py url                             # print RTSP URL (with credentials)
  rtsp_stream.py url --no-auth                   # print URL without credentials
  rtsp_stream.py url --channel 12                # sub stream
  rtsp_stream.py capture                         # save one frame to frame.jpg
  rtsp_stream.py capture --output /tmp/snap.jpg
  rtsp_stream.py record --duration 30            # record 30s to stream.mp4
  rtsp_stream.py record --duration 10 --output clip.mp4 --fps 15
  rtsp_stream.py display                         # live preview window
""",
    )
    parser.add_argument(
        "--channel", type=int, choices=[11, 12, 13], default=11,
        help="Stream channel: 11=main, 12=sub, 13=mobile (default: 11)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # url
    p = sub.add_parser("url", help="Print the RTSP URL for this camera and exit")
    p.add_argument("--no-auth", action="store_true",
                   help="Omit credentials from the URL")

    # capture
    p = sub.add_parser("capture", help="Capture a single frame from the RTSP stream")
    p.add_argument("--output", default="frame.jpg", metavar="FILE",
                   help="Output JPEG path (default: frame.jpg)")

    # record
    p = sub.add_parser("record", help="Record an MP4 clip from the RTSP stream")
    p.add_argument("--duration", type=float, default=10.0, metavar="SEC",
                   help="Recording duration in seconds (default: 10)")
    p.add_argument("--output", default="stream.mp4", metavar="FILE",
                   help="Output MP4 path (default: stream.mp4)")
    p.add_argument("--fps", type=float, default=25.0, dest="fps_limit", metavar="FPS",
                   help="Max FPS cap for output file (default: 25)")

    # display
    sub.add_parser("display", help="Open a live preview window (requires a display)")

    args = parser.parse_args()

    try:
        c = load_config()
    except FileNotFoundError as e:
        err(str(e))
    except Exception as e:
        err(f"Config error: {e}")

    try:
        if args.cmd == "url":
            cmd_url(c, args.channel, getattr(args, "no_auth", False))
        elif args.cmd == "capture":
            cmd_capture(c, args.channel, args.output)
        elif args.cmd == "record":
            cmd_record(c, args.channel, args.output, args.duration, args.fps_limit)
        elif args.cmd == "display":
            cmd_display(c, args.channel)
    except SystemExit:
        raise
    except Exception as e:
        err(str(e))


if __name__ == "__main__":
    main()
