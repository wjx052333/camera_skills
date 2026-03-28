# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the camera CLI

```bash
# Use the venv python (uv also works as per SKILL.toml)
venv/bin/python3 camera-control/scripts/camera.py --help

# Quick connectivity test (runs all gets + saves snapshot.jpg)
venv/bin/python3 camera_control.py
```

## Architecture

This repo contains two layers for the same hi3510 CGI camera API:

| File | Role |
|---|---|
| `camera_control.py` | Library-style Python class (`Camera`). Full API surface including rarely-used calls (reboot, reset, motor config, network, MD). Used for scripting and imports. |
| `camera-control/scripts/camera.py` | CLI entry point. Wraps the same API as a self-contained argparse CLI. This is what the agent skill actually calls. |
| `camera-control/SKILL.toml` | Skill manifest — maps tool names (`camera_snap`, `camera_ptz`, …) to shell commands using `uv run`. |
| `camera-control/SKILL.md` | Human-readable skill docs; also injected as agent context. |
| `SOUL.md` | Agent behavioral specification for zeroclaw. Defines the full runtime loop: capability probe (test each PTZ direction and feature before assuming anything works) → full panoramic environment mapping (PTZ sweep + `home_baseline.jpg`) → standby (static at home position, passive alarm polling) → alarm response (locate alarm angle from tracked PTZ state, analyze `alarmsnap.jpg`, decide whether to slew, track, then return and verify scene consistency). Also covers scene anomaly handling (camera physically moved or angle tampered — never auto-rebuild, always escalate to human) and person identification. |

## Key implementation details

**CGI response format** — The camera returns `var key="value";` lines. `parse_cgi_response()` in the CLI script converts these to a dict. Raw text is returned as-is if no `var` lines are found.

**Alarm detection mechanism** — Motion detection works by comparing the ETag of `/web/tmpfs/alarmsnap.jpg` between calls. State is persisted in `camera-control/scripts/.alarm_state.json`. First call always returns `triggered: false` (establishes baseline). The `watch` subcommand runs this in a polling loop and emits JSON lines to stdout.

**PTZ position** — The API has no position-query endpoint. Any code that needs to track current PTZ position must maintain its own state variable.

**Config** — Camera IP/credentials are in `camera-control/scripts/camera_config.ini`. Both scripts read from their own directory; `camera_control.py` reads from `./camera_config.ini` (repo root).

**Two PTZ APIs** — The camera exposes both `param.cgi?cmd=ptzctrl` (preferred, continuous/step/speed control) and legacy single-action CGIs (`/cgi-bin/hi3510/ptzup.cgi` etc.). The CLI uses only `ptzctrl`.
