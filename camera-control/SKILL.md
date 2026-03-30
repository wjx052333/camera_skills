---
name: camera-control
description: Control an SSAU IP camera (hi3510 CGI API). Use when asked to: move/pan/tilt/zoom the camera, take a photo or snapshot, adjust brightness/contrast/flip/mirror/IR, check for motion, or query camera status. All tools output JSON. Connection settings are in scripts/camera_config.ini.
tags: [camera, iot, vision, hardware]
---

Control the SSAU IP camera via CGI HTTP API. Config is read from `camera_config.ini` next to this skill.

## Usage notes

- Camera IP / credentials → edit `skills/camera-control/scripts/camera_config.ini`
- All tools return `{"ok": true, "result": ...}` on success or `{"ok": false, "error": "..."}` on failure
- PTZ stop: call `camera_ptz` with act=stop before issuing a new direction
- Motion alarm: first call to `camera_alarm` records a baseline (triggered=false); subsequent calls return triggered=true only when a new alarm has fired
- `camera_image_set` flags example: `--brightness 60 --contrast 50 --flip on --mirror off`
- IR modes: auto (sensor-driven), open (always on), close (always off)

## Available scripts

- **`scripts/camera.py`** — Full camera control CLI. Always run with `--help` to see current options.

## Tools

| Tool | Description |
|---|---|
| `camera_info` | Get camera system info: model, firmware version, uptime, SD card status. |
| `camera_snap` | Capture a JPEG snapshot and save to disk. |
| `camera_ptz` | Pan, tilt, or zoom. Actions: up, down, left, right, home, stop, zoomin, zoomout, focusin, focusout, hscan, vscan. |
| `camera_preset` | Save current PTZ position as a numbered preset, or move to a saved preset. |
| `camera_image_get` | Read current image settings: brightness, contrast, saturation, sharpness, hue, flip, mirror, noise, AE mode. |
| `camera_image_set` | Adjust image parameters. Pass only the flags you want to change. |
| `camera_ir_get` | Read the current IR / night-vision mode. |
| `camera_ir_set` | Set the IR / night-vision mode (auto / open / close). |
| `camera_alarm` | Check whether motion has been detected since the last call. |
| `camera_check` | Full health check of all camera functions. Returns per-check pass/fail. Safe to call at any time. |
| `camera_panorama` | 4-position panoramic sweep (left → right → home → up → home). Saves one photo per position. |

## Workflow

Run the script with the appropriate subcommand:

```bash
venv/bin/python3 scripts/camera.py --help
```

### PTZ movement

```bash
# Move: direction = up | down | left | right | home | stop
venv/bin/python3 scripts/camera.py ptz --act <direction> [--speed 1-63]

# Zoom: in | out
venv/bin/python3 scripts/camera.py ptz --act zoomin
venv/bin/python3 scripts/camera.py ptz --act zoomout

# Stop movement
venv/bin/python3 scripts/camera.py ptz --act stop
```

### Presets

```bash
# Save current position as preset N
venv/bin/python3 scripts/camera.py preset --act set --number <N>

# Go to preset N
venv/bin/python3 scripts/camera.py preset --act goto --number <N>
```

### Snapshot

```bash
# Save snapshot to file (default: snapshot.jpg)
venv/bin/python3 scripts/camera.py snapshot [--output <path>]
```

### Image settings

```bash
# Get current image settings
venv/bin/python3 scripts/camera.py image --get

# Set image params (all optional, only pass what you want to change)
venv/bin/python3 scripts/camera.py image \
  [--brightness 0-100] [--contrast 0-100] [--saturation 0-100] \
  [--flip on|off] [--mirror on|off] [--noise 0-100] \
  [--aemode 0-22] [--imgmode 0|1]

# Infrared / IR cut
venv/bin/python3 scripts/camera.py infrared --status auto|open|close
```

### Motion alarm — active query (one-shot)

Compares `alarmsnap.jpg` ETag against stored baseline. Returns `triggered: true` only when a new alarm has fired since the last call. State is persisted in `scripts/.alarm_state.json`.

```bash
# First call: records baseline (triggered: false)
venv/bin/python3 scripts/camera.py alarm

# Subsequent calls: triggered: true if new motion, false if not
venv/bin/python3 scripts/camera.py alarm

# Save the alarm image when triggered
venv/bin/python3 scripts/camera.py alarm --save [--output-dir /tmp]

# Reset baseline (next call will re-baseline)
venv/bin/python3 scripts/camera.py alarm --reset
```

### Motion alarm — background watch (async polling)

Runs indefinitely, emitting a JSON line to stdout for each event. Each new alarm image is saved unless `--no-save` is specified. Kill with SIGINT/SIGTERM.

```bash
# Poll every 2 seconds (default), save snapshots to current dir
venv/bin/python3 scripts/camera.py watch

# Custom interval and output dir
venv/bin/python3 scripts/camera.py watch --interval 5 --output-dir /tmp/alarms

# Only emit events, do not save images
venv/bin/python3 scripts/camera.py watch --no-save
```

Event output format (one JSON per line):
```json
{"ok": true, "event": "started", "interval": 2.0}
{"ok": true, "event": "alarm", "etag": "...", "last_modified": "...", "size_bytes": 217657, "saved_to": "/tmp/alarms/alarm_20260328_160813.jpg"}
{"ok": true, "event": "stopped"}
```

### System info

```bash
# Camera model, firmware, SD card status, uptime
venv/bin/python3 scripts/camera.py info

# Video mode and encoding params
venv/bin/python3 scripts/camera.py video --get
venv/bin/python3 scripts/camera.py venc --channel 11|12|13
```

### Health check

```bash
# Full check: network, info, PTZ (4 directions), snapshot, image settings, IR, alarm
venv/bin/python3 scripts/camera.py check
```

### Panoramic sweep

```bash
# 4-position sweep: left → right → home → up → home, one photo per position
venv/bin/python3 scripts/camera.py panorama --output-dir /tmp/panorama
```

## Output format

All commands print JSON to stdout on success:
```json
{"ok": true, "result": "..."}
```
On error:
```json
{"ok": false, "error": "..."}
```

## Config

Camera IP, username, and password are read from `scripts/camera_config.ini`. Edit that file to change connection settings.
