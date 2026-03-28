"""
SSAU IP Camera CGI Control Script
Based on SSAU-Camera-CGI.doc (hi3510 CGI API)
"""

import configparser
import requests
from requests.auth import HTTPBasicAuth
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "camera_config.ini"


def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    return cfg["camera"]


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
        """Call /cgi-bin/hi3510/param.cgi with cmd and extra params."""
        params = {"cmd": cmd}
        for k, v in kwargs.items():
            params[f"-{k}"] = v
        return self._get("/cgi-bin/hi3510/param.cgi", params=params)

    # ── System info ──────────────────────────────────────────────
    def get_server_info(self):
        """Get camera model, firmware version, uptime, SD card status, etc."""
        return self._cgi("getserverinfo")

    def reboot(self):
        """Reboot the camera."""
        return self._get("/cgi-bin/hi3510/sysreboot.cgi")

    def reset(self):
        """Factory reset the camera."""
        return self._get("/cgi-bin/hi3510/sysreset.cgi")

    # ── Snapshot ─────────────────────────────────────────────────
    def get_snapshot(self):
        """Return raw JPEG bytes of current frame."""
        url = f"{self.base}/web/tmpfs/snap.jpg"
        r = requests.get(url, auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        return r.content

    def save_snapshot(self, path="snapshot.jpg"):
        data = self.get_snapshot()
        with open(path, "wb") as f:
            f.write(data)
        print(f"Snapshot saved to {path} ({len(data)} bytes)")
        return path

    # ── Video encoding ────────────────────────────────────────────
    def get_video_attr(self):
        """Get video mode (resolution combination)."""
        return self._cgi("getvideoattr")

    def set_video_attr(self, videomode, vinorm="P", profile=1):
        """
        vinorm: P=PAL(50Hz), N=NTSC(60Hz)
        profile: 0=baseline, 1=main
        videomode: e.g. 32 (720P_QQ720P_QQ720P)
        """
        return self._cgi("setvideoattr", vinorm=vinorm, profile=profile, videomode=videomode)

    def get_venc_attr(self, channel=11):
        """Get encoding params for channel 11/12/13."""
        return self._cgi("getvencattr", chn=channel)

    def set_venc_attr(self, channel=11, bps=1536, fps=25, brmode=1, imagegrade=1, gop=50):
        """
        channel: 11=main, 12=sub, 13=mobile
        bps: bitrate kbps
        brmode: 0=CBR, 1=VBR
        imagegrade: 1-6
        """
        return self._cgi("setvencattr", chn=channel, bps=bps, fps=fps,
                         brmode=brmode, imagegrade=imagegrade, gop=gop)

    # ── Image settings ────────────────────────────────────────────
    def get_image_attr(self):
        """Get brightness, contrast, saturation, flip, mirror, etc."""
        return self._cgi("getimageattr")

    def set_image_attr(self, **kwargs):
        """
        Supported kwargs: brightness, saturation, contrast, sharpness, hue,
        targety, gamma, flip (on/off), mirror (on/off), noise (0-100),
        aemode (0-22), imgmode (0/1), image_type
        """
        return self._cgi("setimageattr", **kwargs)

    # ── Infrared ──────────────────────────────────────────────────
    def get_infrared(self):
        """Get IR cut status: auto / open / close."""
        return self._cgi("getinfrared")

    def set_infrared(self, status="auto"):
        """status: auto | open | close"""
        return self._cgi("setinfrared", infraredstat=status)

    # ── PTZ control ───────────────────────────────────────────────
    def ptz_ctrl(self, act, speed=45, step=0):
        """
        act: left | right | up | down | home | zoomin | zoomout |
             focusin | focusout | aperturein | apertureout |
             hscan | vscan | stop
        speed: 1-63
        step: 0=continuous, 1=step
        """
        return self._cgi("ptzctrl", step=step, act=act, speed=speed)

    def ptz_up(self, speed=45):
        return self.ptz_ctrl("up", speed)

    def ptz_down(self, speed=45):
        return self.ptz_ctrl("down", speed)

    def ptz_left(self, speed=45):
        return self.ptz_ctrl("left", speed)

    def ptz_right(self, speed=45):
        return self.ptz_ctrl("right", speed)

    def ptz_stop(self):
        return self.ptz_ctrl("stop")

    def ptz_home(self):
        return self.ptz_ctrl("home")

    def ptz_zoom_in(self, speed=45):
        return self.ptz_ctrl("zoomin", speed)

    def ptz_zoom_out(self, speed=45):
        return self.ptz_ctrl("zoomout", speed)

    # Legacy single-step PTZ CGIs
    def ptz_up_cgi(self):
        return self._get("/cgi-bin/hi3510/ptzup.cgi")

    def ptz_down_cgi(self):
        return self._get("/cgi-bin/hi3510/ptzdown.cgi")

    def ptz_left_cgi(self):
        return self._get("/cgi-bin/hi3510/ptzleft.cgi")

    def ptz_right_cgi(self):
        return self._get("/cgi-bin/hi3510/ptzright.cgi")

    def ptz_zoom_in_cgi(self):
        return self._get("/cgi-bin/hi3510/ptzzoomin.cgi")

    def ptz_zoom_out_cgi(self):
        return self._get("/cgi-bin/hi3510/ptzzoomout.cgi")

    # ── PTZ Preset ────────────────────────────────────────────────
    def preset_goto(self, number):
        """Go to preset position."""
        return self._cgi("preset", act="goto", number=number)

    def preset_set(self, number):
        """Save current position as preset."""
        return self._cgi("preset", act="set", status=1, number=number)

    # ── Motor / PTZ config ────────────────────────────────────────
    def get_motor_attr(self):
        return self._cgi("getmotorattr")

    def set_motor_attr(self, panspeed=1, tiltspeed=1, panscan=1, tiltscan=1,
                       movehome="on", ptzalarmmask="on", alarmpresetindex=1):
        return self._cgi("setmotorattr", panspeed=panspeed, tiltspeed=tiltspeed,
                         panscan=panscan, tiltscan=tiltscan, movehome=movehome,
                         ptzalarmmask=ptzalarmmask, alarmpresetindex=alarmpresetindex)

    # ── Network ───────────────────────────────────────────────────
    def get_net_attr(self):
        return self._cgi("getnetattr")

    def get_http_port(self):
        return self._cgi("gethttpport")

    # ── Motion detection ─────────────────────────────────────────
    def get_md_attr(self):
        return self._cgi("getmdattr")

    def get_md_alarm(self, aname="email"):
        return self._cgi("getmdalarm", aname=aname)


# ── Quick test ────────────────────────────────────────────────────
if __name__ == "__main__":
    cam = Camera()
    print(f"Connecting to camera at {cam.base} as '{cam.username}'...\n")

    print("=== Server Info ===")
    try:
        info = cam.get_server_info()
        print(info)
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n=== Video Attr ===")
    try:
        print(cam.get_video_attr())
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n=== Image Attr ===")
    try:
        print(cam.get_image_attr())
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n=== Infrared Status ===")
    try:
        print(cam.get_infrared())
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n=== Venc Attr (main stream) ===")
    try:
        print(cam.get_venc_attr(11))
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n=== Snapshot ===")
    try:
        cam.save_snapshot("snapshot.jpg")
    except Exception as e:
        print(f"FAILED: {e}")
