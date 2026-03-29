# rtsp_face — RTSP 人脸追踪 + PTZ 跟踪

从 hi3510 IP 摄像头 RTSP 流实时检测人脸，用 ByteTracker 追踪，当人脸靠近画面边缘时自动控制 PTZ 跟随。

---

## 文件说明

| 文件 | 说明 |
|---|---|
| `face_tracker.py` | 主程序：RTSP 读流 + 人脸检测 + ByteTracker + PTZ 控制 |
| `camera.py` | 摄像头 CGI API 封装（PTZ / 抓图 / 告警等），被 `face_tracker.py` 导入 |
| `rtsp_stream.py` | RTSP 流工具（抓帧 / 录制 / 预览），独立 CLI |
| `camera_config.ini` | 摄像头 IP、账号、端口配置 |

---

## 环境要求

Python 解释器使用 `/home/wjx/agent_eyes/bot/venv`。

已有：`uniface 3.1.1`、`opencv-python`、`numpy`

**需额外安装：**

```bash
/home/wjx/agent_eyes/bot/venv/bin/pip install supervision
```

sudo apt-get -y install cudnn9-cuda-12
export PATH=/usr/local/cuda-12.8/bin:$PATH
---

## 配置

编辑 `camera_config.ini`：

```ini
[camera]
ip       = 192.168.1.100
username = admin
password = admin
port     = 80
```

RTSP 端口默认 554，如需修改加一行 `rtsp_port = 554`。

---

## 快速开始

```bash
cd /home/wjx/agent_eyes/bot/camera_skills/rtsp_face
```

```bash
# 基本运行（sub 流，PTZ 开启）
/home/wjx/agent_eyes/bot/venv/bin/python3 face_tracker.py

# 带预览窗口（需要 X11）
/home/wjx/agent_eyes/bot/venv/bin/python3 face_tracker.py --display

# 只检测 + 追踪，不控 PTZ
/home/wjx/agent_eyes/bot/venv/bin/python3 face_tracker.py --no-ptz --display

# 用主流（更清晰），调宽边缘触发区
/home/wjx/agent_eyes/bot/venv/bin/python3 face_tracker.py --channel 11 --margin 0.25

# PTZ 速度调低，减少过冲
/home/wjx/agent_eyes/bot/venv/bin/python3 face_tracker.py --speed 20
```

按 `Ctrl-C` 退出；预览窗口按 `q` 退出。退出时自动发送 PTZ stop。

---

## 命令行参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--channel` | `12` | RTSP 流通道：11=主流，12=子流，13=移动流 |
| `--scale` | `0.5` | 检测缩放比例（0.5 = 半分辨率，速度更快） |
| `--margin` | `0.20` | 边缘触发区宽度（占画面比例），超出此区域触发 PTZ |
| `--speed` | `30` | PTZ 速度，范围 1–100 |
| `--no-face-stop` | `30` | 连续多少帧无人脸后停止 PTZ |
| `--display` | 关 | 开启实时预览窗口（需 X11） |
| `--no-ptz` | 关 | 禁用 PTZ 控制，只做检测和追踪 |

---

## 工作原理

### 整体流程

```
RTSP 帧
  │
  ├─ resize (--scale)
  │
  ├─ YOLOv8n 人脸检测
  │
  ├─ ByteTracker 多目标追踪
  │       └─ 输出每个人脸的 tracker_id + bbox
  │
  ├─ PTZ 决策（取面积最大的人脸）
  │       ├─ 计算人脸中心归一化坐标 (cx, cy) ∈ [0,1]²
  │       ├─ 若进入边缘触发区 → 计算应移动方向
  │       └─ 向 PtzController 发送命令（异步）
  │
  └─ 可选：绘制 bbox + 状态叠加 → imshow
```

### 边缘触发区

以 `--margin 0.20` 为例，画面划分为：

```
┌────────────────────────────────┐
│  ← 触发区 (20%) →              │
│  ┌──────────────────────┐      │
│  │                      │      │
│  │     安全区 (60%)      │      │
│  │                      │      │
│  └──────────────────────┘      │
│                                │
└────────────────────────────────┘
```

- 人脸中心进入任意一侧触发区 → 向该方向 PTZ
- 同时触发水平和垂直时，选偏移量更大的轴
- 人脸回到安全区 → 发送 stop
- 连续 `--no-face-stop` 帧无人脸 → 发送 stop

### PTZ 控制

PTZ 命令（left / right / up / down / stop）通过 daemon 线程异步发出，不阻塞 RTSP 读帧循环。状态变化时才发送新命令，避免频繁调用摄像头 HTTP 接口。

### ByteTracker

使用 `supervision.ByteTrack`，与 `video_face/scanner_core.py` 相同的实现，在摄像头移动、短暂遮挡等情况下仍能保持 tracker_id 稳定。

---

## 预览窗口说明

`--display` 模式下画面叠加：

- **彩色矩形框** — 每个 tracker_id 对应固定颜色
- **T{id} 标签** — ByteTracker 分配的追踪 ID
- **绿色矩形** — 安全区边界（超出此区域触发 PTZ）
- **左上角状态栏** — 当前 PTZ 动作 + 检测到的人脸数
- **左下角** — 实时帧率估计

---

## 流通道选择建议

| 通道 | 分辨率 | 适用场景 |
|---|---|---|
| 11（主流） | 高（如 1080p） | 精度优先，需配合 `--scale 0.5` |
| 12（子流）| 中（如 720p） | **推荐**，速度与精度均衡 |
| 13（移动流）| 低 | 极低延迟，人脸较小时效果差 |

---

## 常见问题

**Q: 打开流失败**
检查摄像头 IP 和账号是否正确，确认 RTSP 没有被禁用：
```bash
curl "http://admin:admin@192.168.1.100/cgi-bin/hi3510/param.cgi?cmd=getrtspattr"
```

**Q: PTZ 过冲（转过头了）**
降低速度 `--speed 15` 或缩小边缘区 `--margin 0.15`。

**Q: 检测帧率太低**
使用子流 `--channel 12` 并开启半分辨率 `--scale 0.5`（默认已开启）。

**Q: import supervision 报错**
```bash
/home/wjx/agent_eyes/bot/venv/bin/pip install supervision
```
