---
name: camera-control
description: Control an SSAU IP camera (hi3510 CGI API) — PTZ movement, zoom, presets, snapshot capture, image tuning (brightness/contrast/flip/mirror/IR), video encoding, and system info. Use when asked to move the camera, take a photo/screenshot/snapshot, adjust camera image settings, or query camera status.
---

Control the SSAU IP camera via CGI HTTP API. Config is read from `camera_config.ini` next to this skill.

## Available scripts

- **`scripts/camera.py`** — Full camera control CLI. Always run with `--help` to see current options.

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
