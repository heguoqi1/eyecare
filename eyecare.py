#!/usr/bin/env python3
"""eyecare.py - 程序员护眼 v2（色温 + 亮度 + 对比 + 蓝光 + 休息提醒 + 日落模式）

为什么光改色温不够?
  1. 色温    暖色降蓝，跟随自然光循环
  2. 亮度    屏幕和环境光不匹配 - 眼疲劳主因
  3. 蓝光    460-490 nm 是褪黑素/视网膜关键带，单靠 Kelvin 切不够
  4. 对比度  高对比（#000 on #FFF）长时间阅读 = 睫状肌紧绷
  5. 休息    20-20-20 是有循证支持的护眼习惯

CLI（向后兼容，老 .bat 不用改）:
    python eyecare.py warm [K]                # 切到色温 K（默认 4500）
    python eyecare.py off                    # 还原
    python eyecare.py status                 # 当前状态
    python eyecare.py auto [--tween 5]       # 按时钟自动切换

新增:
    python eyecare.py preset <name>          # focus/code/code-dark/docs/evening/night
    python eyecare.py sunset [--lat ... --lon ...]  # 按当地日出日落切换
    python eyecare.py daemon                 # auto + 20-20-20 后台常驻
    python eyecare.py break [--every 20]     # 20-20-20 提醒循环
    python eyecare.py config                 # 显示配置
    python eyecare.py rebackup               # 重新备份原始 ramp
    python eyecare.py monitors               # 列出显示器
    python eyecare.py selftest               # 数学与逻辑自检

技术：纯标准库（ctypes + json + math + argparse + threading），不需要任何 pip 依赖。仅 Windows。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# 路径常量
HERE = Path(__file__).resolve().parent
BACKUP = HERE / "original_ramp.json"
CONFIG_PATH = HERE / "eyecare_config.json"

# Windows API
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


# ─────────────────────────────────────────────────────────────────────────────
# Windows API 封装
# ─────────────────────────────────────────────────────────────────────────────

def read_ramp() -> list[int]:
    """读桌面 gamma ramp，返回 768 个 16-bit 值（R,G,B 各 256）。"""
    hdc = user32.GetDC(0)
    if not hdc:
        raise RuntimeError("GetDC 失败")
    buf = (wintypes.USHORT * 768)()
    ok = gdi32.GetDeviceGammaRamp(wintypes.HDC(hdc), buf)
    user32.ReleaseDC(0, hdc)
    if not ok:
        raise RuntimeError("无法读取色彩曲线（驱动可能拒绝）")
    return list(buf)


def write_ramp(values: Sequence[int]) -> None:
    """写桌面 gamma ramp，输入 768 个 16-bit 值。"""
    if len(values) != 768:
        raise ValueError(f"ramp 长度必须 768，得到 {len(values)}")
    hdc = user32.GetDC(0)
    if not hdc:
        raise RuntimeError("GetDC 失败")
    buf = (wintypes.USHORT * 768)(*values)
    ok = gdi32.SetDeviceGammaRamp(wintypes.HDC(hdc), buf)
    user32.ReleaseDC(0, hdc)
    if not ok:
        raise RuntimeError("写入失败（驱动不支持或当前有全屏独占应用）")


def list_displays() -> list[dict]:
    """枚举显示器，仅用于信息展示。"""
    class _DD(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("DeviceName", ctypes.c_wchar * 32),
            ("DeviceString", ctypes.c_wchar * 128),
            ("StateFlags", ctypes.c_ulong),
            ("DeviceID", ctypes.c_wchar * 128),
            ("DeviceKey", ctypes.c_wchar * 128),
        ]
    info = _DD()
    info.cb = ctypes.sizeof(info)
    out, i = [], 0
    while user32.EnumDisplayDevicesW(None, i, ctypes.byref(info), 0):
        out.append({
            "name": info.DeviceName,
            "desc": info.DeviceString,
            "flags": info.StateFlags,
        })
        i += 1
    return out


def show_message(text: str, title: str = "护眼提醒", icon: int = 0x40) -> int:
    """弹一个 Windows 消息框（MB_ICONINFORMATION 默认）。"""
    return user32.MessageBoxW(0, text, title, icon)


# ─────────────────────────────────────────────────────────────────────────────
# 色彩数学
# ─────────────────────────────────────────────────────────────────────────────

def kelvin_to_multipliers(temp: float) -> tuple[float, float, float]:
    """色温 K -> (R, G, B) 归一化增益。Tanner Helland 转换。"""
    t = max(1000, min(40000, temp)) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    clamp = lambda v: max(0.0, min(255.0, v))
    r, g, b = clamp(r), clamp(g), clamp(b)
    top = max(r, g, b)
    return r / top, g / top, b / top


def identity_ramp() -> list[int]:
    """恒等 ramp：output[i] = i*257。"""
    return [i * 257 for _ in range(3) for i in range(256)]


def apply_contrast(ramp: Sequence[int], contrast: float) -> list[int]:
    """以 32768 为中心拉低/升高对比。1 不变，< 1 减弱。"""
    mid = 32768
    return [max(0, min(65535, int(round(mid + (v - mid) * contrast)))) for v in ramp]


def apply_brightness(ramp: Sequence[int], brightness: float) -> list[int]:
    """亮度乘子。1 不变，< 1 变暗。保留色彩比例。"""
    return [max(0, min(65535, int(round(v * brightness)))) for v in ramp]


def apply_tint(ramp: Sequence[int], mr: float, mg: float, mb: float) -> list[int]:
    """按通道乘子染色。"""
    out, ms = [], (mr, mg, mb)
    for ch in range(3):
        m, base = ms[ch], ch * 256
        for i in range(256):
            out.append(max(0, min(65535, int(round(ramp[base + i] * m)))))
    return out


def build_ramp_from_params(kelvin: int, brightness: float,
                            contrast: float, blue_cut: float) -> list[int]:
    """identity -> 对比 -> 亮度 -> 染色（蓝切追加到 B 通道）。"""
    ramp = identity_ramp()
    if contrast != 1.0:
        ramp = apply_contrast(ramp, contrast)
    if brightness != 1.0:
        ramp = apply_brightness(ramp, brightness)
    mr, mg, mb = kelvin_to_multipliers(kelvin)
    if blue_cut:
        mb *= (1 - blue_cut)
    return apply_tint(ramp, mr, mg, mb)


# ─────────────────────────────────────────────────────────────────────────────
# Presets
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Preset:
    name: str
    desc: str
    kelvin: int = 6500
    brightness: float = 1.0
    contrast: float = 1.0
    blue_cut: float = 0.0


# 数值调过的依据：
#   - 白天色温不应太黄，否则色觉偏移影响读色、做设计；留 >= 5500K
#   - docs 预设最大幅度降亮+对比，因为白底文档是眼疲劳最大场景
#   - code-dark 保对比 1.0，因深色主题本身对比就低，叠加会糊
#   - night/evening 蓝切加大，载入睡前用（影响褪黑素最强的 460-490nm 带）
PRESETS: dict[str, Preset] = {
    "off": Preset("off", "关闭护眼，还原原始色彩",
                  kelvin=6500, brightness=1.00, contrast=1.00, blue_cut=0.00),
    "focus": Preset("focus", "白天专注（轻度暖色 + 微降亮）",
                    kelvin=5800, brightness=0.92, contrast=0.95, blue_cut=0.05),
    "code": Preset("code", "白天长时间写代码（暖色 + 降亮 + 略降对比）",
                   kelvin=5500, brightness=0.80, contrast=0.90, blue_cut=0.15),
    "code-dark": Preset("code-dark", "深色 IDE 主题（保对比 + 略降蓝）",
                        kelvin=6000, brightness=0.95, contrast=1.00, blue_cut=0.05),
    "docs": Preset("docs", "读文档/网页（白底最伤眼，最大幅度降）",
                   kelvin=4700, brightness=0.60, contrast=0.82, blue_cut=0.30),
    "evening": Preset("evening", "日落后（启动褪黑素）",
                      kelvin=4000, brightness=0.55, contrast=0.82, blue_cut=0.40),
    "night": Preset("night", "深夜（极暖，适合无环境光）",
                    kelvin=3200, brightness=0.40, contrast=0.75, blue_cut=0.55),
}


def get_preset(name: str) -> Preset:
    if name not in PRESETS:
        raise SystemExit(f"未知预设：{name}\n可用：{', '.join(PRESETS)}")
    return PRESETS[name]


def build_ramp(p: Preset) -> list[int]:
    return build_ramp_from_params(p.kelvin, p.brightness, p.contrast, p.blue_cut)


# ─────────────────────────────────────────────────────────────────────────────
# 平滑过渡
# ─────────────────────────────────────────────────────────────────────────────

def tween_apply(from_ramp: Sequence[int], to_ramp: Sequence[int],
                duration_s: float, fps: int = 30) -> None:
    """从 from 平滑过渡到 to，duration_s 秒。ease-out 三次方曲线。"""
    if duration_s <= 0:
        write_ramp(to_ramp)
        return
    steps = max(1, int(duration_s * fps))
    sleep_s = duration_s / steps
    for i in range(1, steps + 1):
        t = i / steps
        eased = 1 - (1 - t) ** 3
        ramp = [int(round(from_ramp[j] + (to_ramp[j] - from_ramp[j]) * eased))
                for j in range(768)]
        write_ramp(ramp)
        if i < steps:
            time.sleep(sleep_s)


# ─────────────────────────────────────────────────────────────────────────────
# 备份 / 还原
# ─────────────────────────────────────────────────────────────────────────────

def backup_original() -> None:
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps(read_ramp()), encoding="utf-8")


def restore_original() -> None:
    if BACKUP.exists():
        write_ramp(json.loads(BACKUP.read_text(encoding="utf-8")))
    else:
        write_ramp(identity_ramp())


# ─────────────────────────────────────────────────────────────────────────────
# 状态
# ─────────────────────────────────────────────────────────────────────────────

def guess_preset(rb: float, gb: float, lum: float) -> str:
    """根据当前 ramp 反推最接近的预设。仅展示用。"""
    candidates = []
    for p in PRESETS.values():
        if p.name == "off":
            continue
        m = build_ramp(p)
        pr = sum(m[0:256]) / max(1, sum(m[512:768]))
        pg = sum(m[256:512]) / max(1, sum(m[512:768]))
        plum = sum(m) / (768 * 65535)
        d = abs(pr - rb) + abs(pg - gb) * 0.5 + abs(plum - lum) * 2
        candidates.append((d, p.name))
    candidates.sort()
    if candidates and candidates[0][0] < 0.15:
        return candidates[0][1]
    return "（自定义/非标准状态）"


def cmd_status() -> None:
    ramp = read_ramp()
    sr = sum(ramp[0:256])
    sg = sum(ramp[256:512])
    sb = sum(ramp[512:768])
    rb = sr / sb if sb else 1
    gb = sg / sb if sb else 1
    lum = sum(ramp) / (768 * 65535)

    print("=== 当前色彩曲线 ===")
    print(f"R 总和 {sr:>10}   G {sg:>10}   B {sb:>10}")
    print(f"R/B = {rb:.3f}   G/B = {gb:.3f}")
    print(f"亮度 ≈ {lum*100:.1f}%   (掉 {(1-lum)*100:.0f}% 亮度)")
    print()
    if BACKUP.exists():
        st = BACKUP.stat()
        age_days = (time.time() - st.st_mtime) / 86400
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
        print(f"原始备份：{mtime}（{age_days:.0f} 天前）")
        if age_days > 30:
            print("  [!] 备份超过 30 天，建议运行: python eyecare.py rebackup")
    else:
        print("尚未备份原始 ramp（首次调色时自动备份）")
    print()
    print(f"推测匹配预设：{guess_preset(rb, gb, lum)}")


# ─────────────────────────────────────────────────────────────────────────────
# 自动调度
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScheduleRule:
    start: int   # 起始小时 0-23
    end: int     # 结束小时 0-23（不含 end）
    preset: str

    def contains(self, hour: int) -> bool:
        if self.start < self.end:
            return self.start <= hour < self.end
        # 跨午夜，例如 22-7
        return hour >= self.start or hour < self.end


# 适合上班族（9:00-18:00）：
#   09:00-16:00 focus   上班高专注时段（办公室亮环境，轻度暖色）
#   16:00-18:00 code    下班前（自然光渐暗，开始暖化）
#   18:00-22:00 evening 下班后（启动褪黑素）
#   22:00-09:00 night   深夜（极暖，适合无环境光）
DEFAULT_SCHEDULE = [
    ScheduleRule(9, 16, "focus"),
    ScheduleRule(16, 18, "code"),
    ScheduleRule(18, 22, "evening"),
    ScheduleRule(22, 9, "night"),
]


def preset_for_hour(hour: int, schedule=None) -> str:
    schedule = schedule or DEFAULT_SCHEDULE
    for r in schedule:
        if r.contains(hour):
            return r.preset
    return "focus"


def sun_times(lat: float, lon: float) -> tuple[float, float]:
    """简化 NOAA 算法，返回今日 (sunrise_h, sunset_h) 浮点本地小时。
    精度 ±3 分钟。包含：太阳赤纬 + Equation of Time + 大气折射（90.833°）。
    适用于 |lat| < 60°。"""
    doy = time.localtime().tm_yday

    # 太阳赤纬 (rad)
    gamma = 2 * math.pi / 365 * (doy - 1)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    # Equation of Time (分钟) - 时差，太阳时与平均时的偏差
    B = 2 * math.pi * (doy - 81) / 365
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

    lat_rad = math.radians(lat)
    # 标准日出/日落对应天顶角 90°50'（含大气折射 + 太阳半径）
    zenith = math.radians(90.833)
    cos_ha = ((math.cos(zenith) - math.sin(lat_rad) * math.sin(decl))
              / (math.cos(lat_rad) * math.cos(decl)))
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.degrees(math.acos(cos_ha))

    # 太阳正午 UTC（带 EOT 修正）
    solar_noon_utc = 12.0 - lon / 15.0 - eot / 60.0

    # 本地时区偏移（Windows 不处理 DST）
    utc_offset = -time.timezone / 3600.0

    sunrise = (solar_noon_utc - ha / 15.0 + utc_offset) % 24
    sunset = (solar_noon_utc + ha / 15.0 + utc_offset) % 24
    return sunrise, sunset


# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "auto": {
        "tween_seconds": 5,
        "sunset_mode": False,
        "lat": 31.23,
        "lon": 121.47,
        "schedule": [
            {"start": 9, "end": 16, "preset": "focus"},
            {"start": 16, "end": 18, "preset": "code"},
            {"start": 18, "end": 22, "preset": "evening"},
            {"start": 22, "end": 9, "preset": "night"},
        ],
    },
    "break": {
        "interval_min": 20,
        "duration_s": 20,
    },
}


def _deep_merge(defaults: dict, override: dict) -> dict:
    out = json.loads(json.dumps(defaults))
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return _deep_merge(DEFAULT_CONFIG,
                               json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 命令实现
# ─────────────────────────────────────────────────────────────────────────────

def cmd_warm(kelvin: int) -> None:
    backup_original()
    p = Preset(name="warm", desc=f"用户设定 {kelvin}K",
               kelvin=kelvin, brightness=0.85, contrast=0.92, blue_cut=0.15)
    write_ramp(build_ramp(p))
    mr, mg, mb = kelvin_to_multipliers(kelvin)
    print(f"已切到 {kelvin}K  Rx{mr:.2f} Gx{mg:.2f} Bx{mb:.2f}")
    print("  亮度 -15%, 对比 -8%, 蓝切 -15%  （比 v1 多 4 维保护）")
    print("  还原：python eyecare.py off")


def cmd_off() -> None:
    restore_original()
    msg = "已还原原始色彩"
    if not BACKUP.exists():
        msg += "（无备份，按恒等 ramp 还原）"
    print(msg)


def cmd_preset(name: str, tween_s: float) -> None:
    p = get_preset(name)
    backup_original()
    target = build_ramp(p)
    if tween_s > 0:
        tween_apply(read_ramp(), target, tween_s)
    else:
        write_ramp(target)
    print(f"{p.name} — {p.desc}")
    print(f"  色温 {p.kelvin}K | 亮度 {p.brightness:.0%} "
          f"| 对比 {p.contrast:.0%} | 蓝切 {p.blue_cut:.0%}")


def cmd_auto(tween_s: float) -> None:
    cfg = load_config()
    schedule = [ScheduleRule(r["start"], r["end"], r["preset"])
                for r in cfg["auto"]["schedule"]]
    backup_original()
    print(f"自动模式启动（Ctrl+C 退出）：平移 {tween_s}s")
    for r in schedule:
        s, e = f"{r.start:02d}:00", f"{r.end:02d}:00"
        print(f"  {s} - {e}  ->  {r.preset}  ({PRESETS[r.preset].desc})")
    last = None
    try:
        while True:
            h = time.localtime().tm_hour
            name = preset_for_hour(h, schedule)
            if name != last:
                p = get_preset(name)
                tween_apply(read_ramp(), build_ramp(p), tween_s)
                print(f"[{time.strftime('%H:%M')}] -> {name}")
                last = name
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n还原原始色彩...")
        restore_original()


def cmd_sunset(lat: float | None, lon: float | None, tween_s: float) -> None:
    cfg = load_config()
    if lat is None:
        lat = cfg["auto"].get("lat", 31.23)
    if lon is None:
        lon = cfg["auto"].get("lon", 121.47)
    backup_original()
    print(f"日落模式（Ctrl+C 退出）：lat={lat}, lon={lon}, 平移 {tween_s}s")
    last = None
    try:
        while True:
            sr_h, ss_h = sun_times(lat, lon)
            now = time.localtime()
            h = now.tm_hour + now.tm_min / 60.0
            # 异常时段（极昼极夜）回退 clock 模式
            if ss_h <= sr_h or (ss_h - sr_h) < 1:
                pname = preset_for_hour(int(h))
                tag = " [clock fallback]"
            else:
                tag = ""
                if h < sr_h or h >= ss_h:
                    pname = "night"
                elif h >= ss_h - 1:
                    pname = "evening"
                else:
                    pname = "focus"
            if pname != last:
                p = get_preset(pname)
                tween_apply(read_ramp(), build_ramp(p), tween_s)
                print(f"[{time.strftime('%H:%M')}] 日出 {sr_h:.2f} "
                      f"日落 {ss_h:.2f} -> {pname}{tag}")
                last = pname
            time.sleep(180)
    except KeyboardInterrupt:
        restore_original()


def cmd_break(every_min: int, duration_s: int) -> None:
    msg = (
        f"护眼提醒：看向 6 米外的物体 {duration_s} 秒。\n\n"
        "睫状肌长时间聚焦近处会疲劳。\n"
        "看远处是唯一被反复证实的预防近视/眼疲劳的方法。\n\n"
        "看完后点击「确定」。"
    )
    print(f"20-20-20 提醒：每 {every_min} 分钟一次，Ctrl+C 退出")
    next_t = time.time() + every_min * 60
    try:
        while True:
            if time.time() >= next_t:
                print(f"[{time.strftime('%H:%M')}] 休息提醒")
                show_message(msg, "护眼 20-20-20")
                next_t = time.time() + every_min * 60
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n已退出提醒")


def cmd_daemon() -> None:
    """auto + break 两个线程同时跑。"""
    import threading

    cfg = load_config()
    tween = cfg["auto"].get("tween_seconds", 5)
    interval = cfg["break"].get("interval_min", 20)
    duration = cfg["break"].get("duration_s", 20)
    schedule = [ScheduleRule(r["start"], r["end"], r["preset"])
                for r in cfg["auto"]["schedule"]]

    backup_original()
    print(f"守护模式启动（Ctrl+C 退出）：auto 平移 {tween}s + 提醒每 {interval}min")
    print("今日时间表：")
    for r in schedule:
        s, e = f"{r.start:02d}:00", f"{r.end:02d}:00"
        wrap = "  (跨午夜)" if r.start >= r.end else ""
        print(f"  {s}-{e}  ->  {r.preset:8} ({PRESETS[r.preset].desc}){wrap}")

    stop = threading.Event()

    def auto_loop():
        last = None
        while not stop.is_set():
            h = time.localtime().tm_hour
            name = preset_for_hour(h, schedule)
            if name != last:
                p = get_preset(name)
                try:
                    tween_apply(read_ramp(), build_ramp(p), tween)
                    print(f"[{time.strftime('%H:%M')}] auto -> {name}")
                except Exception as e:
                    print(f"auto 错误：{e}")
                last = name
            stop.wait(30)

    def break_loop():
        next_t = time.time() + interval * 60
        while not stop.is_set():
            if time.time() >= next_t:
                try:
                    print(f"[{time.strftime('%H:%M')}] 休息提醒")
                    show_message(
                        f"护眼提醒：看向 6 米外的物体 {duration} 秒。\n\n"
                        "看完后点击「确定」。",
                        "护眼 20-20-20",
                    )
                except Exception as e:
                    print(f"提醒错误：{e}")
                next_t = time.time() + interval * 60
            stop.wait(5)

    t1 = threading.Thread(target=auto_loop, daemon=True, name="auto")
    t2 = threading.Thread(target=break_loop, daemon=True, name="break")
    t1.start()
    t2.start()
    try:
        while not stop.is_set():
            stop.wait(1)
    except KeyboardInterrupt:
        print("\n还原...")
        stop.set()
        t1.join(timeout=2)
        t2.join(timeout=2)
        restore_original()


def cmd_rebackup() -> None:
    if BACKUP.exists():
        BACKUP.unlink()
    backup_original()
    print(f"已重新备份原始 ramp：{BACKUP}")


def cmd_print_config() -> None:
    print(f"配置：{CONFIG_PATH}")
    print(json.dumps(load_config(), indent=2, ensure_ascii=False))


def cmd_print_monitors() -> None:
    for i, d in enumerate(list_displays()):
        flag = "[active]" if (d["flags"] & 1) else "[disabled]"
        print(f"  {i}  {d['name']:20}  {flag}  {d['desc']}")


def cmd_selftest() -> None:
    """数学与逻辑自检，不动屏幕。"""
    print("=== 自检 ===")
    # 色彩数学
    mr, mg, mb = kelvin_to_multipliers(6500)
    assert abs(mr - 1) < 0.05, f"6500K R≠1: {mr}"
    mr, mg, mb = kelvin_to_multipliers(3000)
    assert mr > mg > mb, f"3000K 通道顺序错：{mr},{mg},{mb}"
    print("  [ok] Kelvin 公式")
    # 恒等 ramp
    r = identity_ramp()
    assert len(r) == 768 and r[0] == 0 and r[255] == 65535 and r[256] == 0
    print("  [ok] identity ramp")
    # contrast / brightness
    rc = apply_contrast(r, 0.5)
    assert 0 < rc[0] < 32768
    assert abs(rc[128] - 32768) < 200
    rb = apply_brightness(r, 0.5)
    assert abs(rb[255] - 32768) <= 2
    print("  [ok] contrast / brightness 应用")
    # 全部预设可生成合法 ramp
    for name, p in PRESETS.items():
        ramp = build_ramp(p)
        assert len(ramp) == 768 and all(0 <= v <= 65535 for v in ramp)
    print(f"  [ok] {len(PRESETS)} 个预设 ramp 全部合法")
    # 调度覆盖 24h
    sched = DEFAULT_SCHEDULE
    for h in range(24):
        assert preset_for_hour(h, sched) in {"focus", "code", "evening", "night"}
    print("  [ok] 调度逻辑覆盖 24h")
    # sun_times 输出范围
    sr, ss = sun_times(31.23, 121.47)
    assert 0 <= sr < 24 and 0 <= ss < 24 and ss > sr
    print(f"  [ok] sun_times(上海) = {sr:.2f}/{ss:.2f}")
    print("\n全部通过 [OK]")


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    parser = argparse.ArgumentParser(
        description="程序员护眼 v2（Windows GDI gamma ramp + 休息提醒）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("off", aliases=["reset"], help="还原原始色彩")
    sub.add_parser("status", help="查看当前状态")
    sub.add_parser("rebackup", help="重新备份原始 ramp")
    sub.add_parser("config", help="显示配置")
    sub.add_parser("monitors", help="列出显示器")
    sub.add_parser("selftest", help="自检（不动屏幕）")

    p_warm = sub.add_parser("warm", help="切到指定色温")
    p_warm.add_argument("kelvin", nargs="?", type=int, default=4500)

    p_preset = sub.add_parser("preset", help="用预设")
    p_preset.add_argument("name")
    p_preset.add_argument("--tween", type=float, default=0, help="过渡秒数")

    p_auto = sub.add_parser("auto", help="按时钟自动切换")
    p_auto.add_argument("--tween", type=float, default=5)

    p_sunset = sub.add_parser("sunset", help="按当地日落切换")
    p_sunset.add_argument("--lat", type=float)
    p_sunset.add_argument("--lon", type=float)
    p_sunset.add_argument("--tween", type=float, default=5)

    p_break = sub.add_parser("break", help="20-20-20 提醒循环")
    p_break.add_argument("--every", type=int, default=20)
    p_break.add_argument("--duration", type=int, default=20)

    sub.add_parser("daemon", help="auto + 20-20-20 后台常驻")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    try:
        c = args.cmd
        if c in ("off", "reset"):
            cmd_off()
        elif c == "status":
            cmd_status()
        elif c == "warm":
            cmd_warm(args.kelvin)
        elif c == "preset":
            cmd_preset(args.name, args.tween)
        elif c == "auto":
            cmd_auto(args.tween)
        elif c == "sunset":
            cmd_sunset(args.lat, args.lon, args.tween)
        elif c == "break":
            cmd_break(args.every, args.duration)
        elif c == "daemon":
            cmd_daemon()
        elif c == "rebackup":
            cmd_rebackup()
        elif c == "config":
            cmd_print_config()
        elif c == "monitors":
            cmd_print_monitors()
        elif c == "selftest":
            cmd_selftest()
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        print("\n中断")
        return 130
    except SystemExit as e:
        return int(getattr(e, "code", 1))
    except Exception as e:
        print(f"出错：{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))