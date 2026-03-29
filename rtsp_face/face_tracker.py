#!/home/wjx/agent_eyes/bot/venv/bin/python3
"""
RTSP face tracking with PTZ control for hi3510 IP camera.

Reads RTSP stream, detects faces with uniface YOLOv8n, tracks
them with ByteTracker, and pans/tilts the camera when a face
approaches the frame edge.

Usage:
  python face_tracker.py [--channel {11,12,13}] [--margin 0.2]
                         [--speed 30] [--scale 0.5]
                         [--display] [--no-ptz]

Exit: Ctrl-C or press 'q' in the display window.
"""

import sys
import time
import threading
import argparse
from pathlib import Path

import cv2
import numpy as np
from supervision import ByteTrack, Detections as SvDetections

# Import Camera from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from camera import Camera, load_config  # noqa: E402

# ── Latest-frame reader thread ────────────────────────────────────────────────

class FrameReader:
    """Background thread that continuously grabs from the RTSP stream and
    keeps only the most recent decoded frame.  The main loop calls `read()`
    which returns (True, frame) immediately without waiting for the next
    network packet — so processing lag never accumulates a backlog."""

    def __init__(self, cap: cv2.VideoCapture):
        self._cap   = cap
        self._lock  = threading.Lock()
        self._frame: np.ndarray | None = None
        self._ok    = True   # assume ok; thread sets False only on read failure
        self._stop  = False
        self._grabbed = 0   # total frames grabbed by background thread
        self._dropped = 0   # frames grabbed but overwritten before main read
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        while not self._stop:
            ok, frame = self._cap.read()
            with self._lock:
                if self._frame is not None:
                    self._dropped += 1  # previous frame never consumed
                self._ok    = ok
                self._frame = frame
                self._grabbed += 1
            if not ok:
                break

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Block until a fresh frame is available, then return (True, frame).
        Returns (False, None) only when the background thread signals stream end."""
        while True:
            with self._lock:
                if self._frame is not None:
                    frame, self._frame = self._frame, None
                    return True, frame
                if not self._ok:          # thread set False → stream ended
                    return False, None
            time.sleep(0.002)

    def stats(self) -> tuple[int, int]:
        with self._lock:
            return self._grabbed, self._dropped

    def stop(self) -> None:
        self._stop = True


# ── Detector init ─────────────────────────────────────────────────────────────

def _make_detector():
    from uniface.detection import YOLOv8Face
    from uniface.detection.yolov8 import YOLOv8FaceWeights
    return YOLOv8Face(model_name=YOLOv8FaceWeights.YOLOV8N)


# ── PTZ controller ────────────────────────────────────────────────────────────

class PtzController:
    """Non-blocking PTZ wrapper. Sends commands in a background thread so the
    RTSP read loop is never stalled waiting for the camera HTTP response."""

    def __init__(self, camera: Camera, speed: int = 30):
        self.camera = camera
        self.speed = speed
        self._lock = threading.Lock()
        self._current: str | None = None   # last successfully sent action
        self._desired: str | None = None   # latest desired action (may differ)
        self._thread: threading.Thread | None = None

    def request(self, action: str | None) -> None:
        """Request a PTZ action. Pass None or 'stop' to stop movement.
        Returns immediately; command is delivered in background."""
        action = action or "stop"
        with self._lock:
            if action == self._current and action == self._desired:
                return          # already doing this; no-op
            self._desired = action
        if self._thread is None or not self._thread.is_alive():
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._thread = t

    def _worker(self) -> None:
        while True:
            with self._lock:
                desired = self._desired
            if desired is None or desired == self._current:
                break
            try:
                self.camera.ptz_ctrl(desired, speed=self.speed)
                with self._lock:
                    prev = self._current
                    self._current = desired
                if prev != desired:
                    print(f"[PTZ] {prev or 'stop'} → {desired}", flush=True)
            except Exception as e:
                print(f"[PTZ] error sending '{desired}': {e}", flush=True)
                break
            time.sleep(0.05)

    def stop_now(self) -> None:
        """Blocking stop — called on exit."""
        print("[PTZ] sending stop on exit", flush=True)
        try:
            self.camera.ptz_ctrl("stop", speed=self.speed)
        except Exception as e:
            print(f"[PTZ] stop_now error: {e}", flush=True)


# ── PTZ decision logic ────────────────────────────────────────────────────────

def decide_ptz(cx_norm: float, cy_norm: float, margin: float) -> str | None:
    """Return the single most-urgent PTZ action, or None if face is centered.

    cx_norm / cy_norm: face-center as fraction of frame width/height (0..1).
    margin: edge zone width as fraction (e.g. 0.20 = outer 20% triggers PTZ).

    When both horizontal and vertical adjustments are needed, the axis with
    the larger deviation is chosen so each frame makes progress on the worst
    direction.
    """
    h_dev, v_dev = 0.0, 0.0
    h_act, v_act = None, None

    if cx_norm < margin:
        h_act = "left"
        h_dev = margin - cx_norm
    elif cx_norm > 1.0 - margin:
        h_act = "right"
        h_dev = cx_norm - (1.0 - margin)

    if cy_norm < margin:
        v_act = "up"
        v_dev = margin - cy_norm
    elif cy_norm > 1.0 - margin:
        v_act = "down"
        v_dev = cy_norm - (1.0 - margin)

    if h_dev == 0 and v_dev == 0:
        return None
    return h_act if h_dev >= v_dev else v_act


# ── Palette for tracker-ID colours ───────────────────────────────────────────

_PALETTE = [
    (0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255),
    (255, 0, 255), (255, 255, 0), (128, 0, 255), (255, 128, 0),
    (0, 128, 255), (128, 255, 0), (64, 64, 255), (255, 64, 64),
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RTSP face tracker with PTZ follow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python face_tracker.py                        # sub stream, PTZ on
  python face_tracker.py --display              # show live window
  python face_tracker.py --no-ptz --display     # detect & track only, no PTZ
  python face_tracker.py --channel 11 --speed 45
""",
    )
    parser.add_argument("--channel", type=int, choices=[11, 12, 13], default=12,
                        help="RTSP channel: 11=main, 12=sub, 13=mobile (default: 12)")
    parser.add_argument("--scale", type=float, default=0.5,
                        help="Detection scale (0.5 = half res, faster) (default: 0.5)")
    parser.add_argument("--margin", type=float, default=0.20,
                        help="Edge margin fraction that triggers PTZ (default: 0.20)")
    parser.add_argument("--speed", type=int, default=30,
                        help="PTZ speed 1-100 (default: 30)")
    parser.add_argument("--no-face-stop", type=int, default=30,
                        help="Frames without a face before stopping PTZ (default: 30)")
    parser.add_argument("--skip", type=int, default=1,
                        help="Run detection every N frames; tracker uses last result "
                             "on skipped frames (default: 1 = no skip)")
    parser.add_argument("--display", action="store_true",
                        help="Open a live preview window (requires X11)")
    parser.add_argument("--no-ptz", action="store_true",
                        help="Disable PTZ control (detection + tracking only)")
    args = parser.parse_args()

    # Config
    c = load_config()
    ip = c["ip"]
    port = c.getint("rtsp_port", fallback=554)
    user = c["username"]
    passwd = c["password"]
    rtsp_url = f"rtsp://{user}:{passwd}@{ip}:{port}/{args.channel}"

    print(f"[init] detector: YOLOv8n  tracker: ByteTrack  scale: {args.scale}  "
          f"skip: every {args.skip} frame(s)")
    print(f"[init] RTSP: rtsp://{ip}:{port}/{args.channel}  margin: {args.margin:.0%}  "
          f"PTZ speed: {args.speed}  PTZ: {'off' if args.no_ptz else 'on'}")
    print(f"[init] no-face PTZ stop after {args.no_face_stop} frames")

    print("[init] loading YOLOv8n detector ...", flush=True)
    detector = _make_detector()
    print("[init] detector ready", flush=True)

    tracker  = ByteTrack(frame_rate=15)
    print("[init] ByteTrack ready", flush=True)

    ptz: PtzController | None = None
    if not args.no_ptz:
        ptz = PtzController(Camera(), speed=args.speed)
        print(f"[init] PTZ controller ready  camera={ip}:{c.getint('port', fallback=80)}",
              flush=True)

    print(f"[stream] opening RTSP stream ...", flush=True)
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print(f"[error] cannot open RTSP stream: rtsp://{ip}:{port}/{args.channel}",
              file=sys.stderr)
        sys.exit(1)

    # Get frame dimensions from first frame
    ret, frame = cap.read()
    if not ret:
        print("[error] failed to read first frame", file=sys.stderr)
        cap.release()
        sys.exit(1)

    fh, fw = frame.shape[:2]
    if args.scale != 1.0:
        det_w = max(1, int(fw * args.scale))
        det_h = max(1, int(fh * args.scale))
        inv_s = 1.0 / args.scale
    else:
        det_w, det_h, inv_s = fw, fh, 1.0

    print(f"[stream] connected  frame: {fw}x{fh}  detect: {det_w}x{det_h}")
    print("[stream] running — Ctrl-C to exit", flush=True)

    reader = FrameReader(cap)
    print("[stream] frame reader thread started", flush=True)

    no_face_frames = 0
    frame_count    = 0
    t_start        = time.monotonic()
    _last_stat_t   = t_start        # for periodic fps log
    _last_stat_f   = 0
    _prev_action   = "stop"         # for detecting PTZ state changes in log
    _prev_n_faces  = 0              # for detecting face-count changes in log
    _last_faces: list = []          # detection result reused on skipped frames
    _last_confs:  np.ndarray = np.empty(0, dtype=np.float32)

    # Per-stage timing accumulators (seconds, reset each stat interval)
    _t = {"read": 0.0, "resize": 0.0, "detect": 0.0,
          "tracker": 0.0, "ptz": 0.0, "display": 0.0}
    _n_detect = 0   # detection calls in interval

    try:
        while True:
            _ts = time.perf_counter()
            ret, frame = reader.read()
            _t["read"] += time.perf_counter() - _ts
            if not ret:
                print("[stream] ended or read error")
                break
            frame_count += 1

            # Periodic fps / status log every 5 s
            now = time.monotonic()
            if now - _last_stat_t >= 5.0:
                interval  = now - _last_stat_t
                fps_now   = (frame_count - _last_stat_f) / interval
                elapsed   = now - t_start
                grabbed, dropped = reader.stats()
                t_sum = sum(_t.values()) or 1e-9
                timing = "  ".join(
                    f"{k}={v*1000/max(1,frame_count-_last_stat_f):.1f}ms"
                    for k, v in _t.items()
                )
                print(f"[stat] t={elapsed:.0f}s  frame={frame_count}  "
                      f"fps={fps_now:.1f}  grabbed={grabbed}  dropped={dropped}  "
                      f"no_face_streak={no_face_frames}",
                      flush=True)
                print(f"[stat] timing/frame — {timing}  "
                      f"detect_calls={_n_detect}",
                      flush=True)
                _last_stat_t = now
                _last_stat_f = frame_count
                for k in _t:
                    _t[k] = 0.0
                _n_detect = 0

            # ── Detection (with optional frame skip) ─────────────────────────
            _ts = time.perf_counter()
            det_frame = (cv2.resize(frame, (det_w, det_h))
                         if args.scale != 1.0 else frame)
            _t["resize"] += time.perf_counter() - _ts

            do_detect = (frame_count % args.skip == 1) if args.skip > 1 else True
            if do_detect:
                _ts = time.perf_counter()
                try:
                    _last_faces = detector.detect(det_frame)
                    if _last_faces:
                        _last_confs = np.array([float(f.confidence)
                                                for f in _last_faces],
                                               dtype=np.float32)
                    else:
                        _last_confs = np.empty(0, dtype=np.float32)
                except Exception as e:
                    print(f"[warn] detection error frame {frame_count}: {e}")
                    continue
                finally:
                    _t["detect"] += time.perf_counter() - _ts
                _n_detect += 1
            # else: reuse _last_faces / _last_confs from previous detect frame

            faces = _last_faces
            n_raw = len(faces) if faces else 0

            # Build supervision Detections (empty if no faces)
            if faces:
                bboxes = np.array([f.bbox for f in faces], dtype=np.float32)
                confs  = _last_confs
            else:
                bboxes = np.empty((0, 4), dtype=np.float32)
                confs  = np.empty(0, dtype=np.float32)

            _ts = time.perf_counter()
            sv_dets = SvDetections(xyxy=bboxes, confidence=confs)
            tracked = tracker.update_with_detections(sv_dets)
            _t["tracker"] += time.perf_counter() - _ts

            has_faces = (tracked.tracker_id is not None and len(tracked) > 0)
            n_tracked = len(tracked) if has_faces else 0

            # Log when face count changes
            if n_tracked != _prev_n_faces:
                if n_tracked == 0:
                    print(f"[track] frame={frame_count}  faces lost "
                          f"(raw={n_raw}  tracked→0)", flush=True)
                else:
                    tids = [int(tracked.tracker_id[i]) for i in range(n_tracked)]
                    print(f"[track] frame={frame_count}  faces={n_tracked} "
                          f"raw={n_raw}  ids={tids}", flush=True)
                _prev_n_faces = n_tracked

            # ── PTZ decision ─────────────────────────────────────────────────
            if has_faces:
                no_face_frames = 0

                # Track the largest (most prominent) face for PTZ
                best_area  = -1.0
                best_cx_n  = 0.5
                best_cy_n  = 0.5

                disp = frame.copy() if args.display else None

                for i in range(len(tracked)):
                    x1, y1, x2, y2 = tracked.xyxy[i]
                    tid = int(tracked.tracker_id[i])

                    # Scale bboxes back to original-frame coords
                    ox1, oy1 = int(x1 * inv_s), int(y1 * inv_s)
                    ox2, oy2 = int(x2 * inv_s), int(y2 * inv_s)
                    area = float((ox2 - ox1) * (oy2 - oy1))

                    cx_n = ((ox1 + ox2) / 2.0) / fw
                    cy_n = ((oy1 + oy2) / 2.0) / fh

                    if area > best_area:
                        best_area = area
                        best_cx_n = cx_n
                        best_cy_n = cy_n

                    if disp is not None:
                        color = _PALETTE[tid % len(_PALETTE)]
                        cv2.rectangle(disp, (ox1, oy1), (ox2, oy2), color, 2)
                        cv2.putText(disp, f"T{tid}",
                                    (ox1, max(0, oy1 - 6)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1,
                                    cv2.LINE_AA)

                action = decide_ptz(best_cx_n, best_cy_n, args.margin)
                _ts = time.perf_counter()
                if ptz:
                    ptz.request(action)
                _t["ptz"] += time.perf_counter() - _ts

                # Log PTZ action changes
                cur_action = action or "stop"
                if cur_action != _prev_action:
                    print(f"[track] frame={frame_count}  primary face "
                          f"cx={best_cx_n:.2f} cy={best_cy_n:.2f}  "
                          f"PTZ: {_prev_action} → {cur_action}", flush=True)
                    _prev_action = cur_action

                if disp is not None:
                    _ts = time.perf_counter()
                    # Draw safe-zone rectangle
                    mx, my = int(fw * args.margin), int(fh * args.margin)
                    cv2.rectangle(disp, (mx, my), (fw - mx, fh - my),
                                  (0, 255, 0), 1)
                    status = f"PTZ: {action or 'stop'}  faces: {len(tracked)}"
                    cv2.putText(disp, status, (10, 28),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2,
                                cv2.LINE_AA)
                    fps_est = frame_count / max(0.01, time.monotonic() - t_start)
                    cv2.putText(disp, f"{fps_est:.1f} fps", (10, fh - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1,
                                cv2.LINE_AA)
                    cv2.imshow("Face Tracker", disp)
                    _t["display"] += time.perf_counter() - _ts
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

            else:
                # No tracked face
                no_face_frames += 1
                if ptz and no_face_frames == args.no_face_stop:
                    print(f"[track] frame={frame_count}  no face for "
                          f"{no_face_frames} frames — stopping PTZ", flush=True)
                    _ts = time.perf_counter()
                    ptz.request(None)   # stop PTZ
                    _t["ptz"] += time.perf_counter() - _ts
                    _prev_action = "stop"

                if args.display:
                    _ts = time.perf_counter()
                    cv2.imshow("Face Tracker", frame)
                    _t["display"] += time.perf_counter() - _ts
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

    except KeyboardInterrupt:
        print("\n[exit] interrupted")
    finally:
        reader.stop()
        if ptz:
            ptz.stop_now()
        cap.release()
        if args.display:
            cv2.destroyAllWindows()
        elapsed = time.monotonic() - t_start
        if elapsed > 0:
            print(f"[exit] {frame_count} frames in {elapsed:.1f}s "
                  f"({frame_count/elapsed:.1f} fps avg)")


if __name__ == "__main__":
    main()
