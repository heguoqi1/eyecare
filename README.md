# 程序员护眼 (eyecare.py)

> **Windows GDI gamma ramp + 20-20-20 提醒 + 日落算法，0 依赖、纯标准库。**
> 适用人群：程序员 + 任何长时间盯屏幕的人。

---

## TL;DR：30 秒上手

最快的方法 —— **双击 `守护模式.bat`**。

它会按下面这套时间表自动调色，每段切换有 5 秒平滑过渡；每 20 分钟弹一次窗提醒看远方。关掉就 `Ctrl+C`，屏幕自动还原。

| 时段 | 预设 | 适用场景 |
|---|---|---|
| 09:00-16:00 | focus | 办公室白天（亮环境）|
| 16:00-18:00 | code | 下班前（自然光渐暗）|
| 18:00-22:00 | evening | 下班后 |
| 22:00-09:00 | night | 深夜 |

需要立刻切档？双击 `护眼-专注.bat` / `护眼-代码.bat` / `护眼-阅读.bat` 等任何一个。要还原？`护眼关.bat`。

---

## 目录

- [1. 设计思想：护眼不止色温](#1-设计思想护眼不止色温)
- [2. 安装与运行](#2-安装与运行)
- [3. CLI 命令参考](#3-cli-命令参考)
- [4. 一键脚本](#4-一键脚本)
- [5. 7 个预设](#5-7-个预设)
- [6. 守护模式详解](#6-守护模式详解)
- [7. 自动模式时间表](#7-自动模式时间表)
- [8. 休息提醒（20-20-20）](#8-休息提醒20-20-20)
- [9. 日落模式](#9-日落模式)
- [10. 配置（eyecare_config.json）](#10-配置eyecare_configjson)
- [11. 工作原理](#11-工作原理)
- [12. 调参建议](#12-调参建议)
- [13. 故障排除](#13-故障排除)
- [14. 文件清单](#14-文件清单)

---

## 1. 设计思想：护眼不止色温

眼疲劳的成因，按对人体工程学影响排序：

| 因素 | 对什么影响大 | v1（原版）| v2（这个）|
|---|---|---|---|
| 屏幕 vs 环境光亮度差 | **最大头**，眼睛反复调瞳孔 | ❌ | ✅ 亮度乘子 |
| 高对比文本（`#000` on `#FFF`）| 睫状肌持续紧绷 | ❌ | ✅ 对比度压缩 |
| 460-490nm 蓝光 | 褪黑素抑制 + 视网膜 | ❌（光改色温切不够）| ✅ 额外蓝切 |
| 20-20-20 休息缺失 | **唯一强循证** | ❌ | ✅ 弹窗循环 |
| 色温 | 中等 | ✅ | ✅ |

v1 = 只动色温，等于把所有鸡蛋放一个篮子里。
v2 = 5 个维度同时动，效果叠加。

**程序员护眼的特殊之处**：

- **看代码 = 高对比文字**（光标闪、语法高亮、眼球追焦最累）
- **长时间持续**，不像刷网页有节奏
- **晚间加班率高**，影响褪黑素 → 影响睡眠 → 影响第二天注意力 → 又累眼

所以本工具的核心场景：保护长时间盯 IDE / 文档的程序员眼。

---

## 2. 安装与运行

### 要求

- **仅 Windows**（用 GDI `SetDeviceGammaRamp`）
- **Python 3.10+**（用了 PEP 604 `int | None` 语法）
- **0 依赖**：纯标准库，无需 `pip install` 任何东西

### 运行

```powershell
cd D:\npy-demo\eyecare
python eyecare.py --help
```

### 第一次跑

第一次跑任何会改屏的命令（如 `warm`、`preset`、`auto`、`daemon` 等）时，工具会自动备份当前的 gamma ramp 到 `original_ramp.json`。以后 `off` 还原就是按这个文件。

如果以后换了显示器色彩配置文件，建议跑：

```powershell
python eyecare.py rebackup
```

### 自检

不放心？跑一下：

```powershell
python eyecare.py selftest
```

会验色彩数学、ramps、调度逻辑、sun_times 输出，不动屏幕。

---

## 3. CLI 命令参考

```
python eyecare.py warm [kelvin]              # 切到色温 K（默认 4500），含轻度亮度/对比/蓝光衰减
python eyecare.py off                        # 还原
python eyecare.py status                     # 当前色温/亮度/对比度/蓝光估计 + 推测预设
python eyecare.py auto [--tween 5]           # 按时钟自动切换（平滑过渡）

python eyecare.py preset <name>              # 用预设: focus/code/code-dark/docs/evening/night/off
python eyecare.py sunset [--lat ... --lon ...]  # 按当地日出日落自动切
python eyecare.py daemon                     # auto + 20-20-20 后台常驻
python eyecare.py break [--every 20]         # 20-20-20 提醒循环
python eyecare.py config                     # 显示配置
python eyecare.py rebackup                   # 重新备份原始 ramp
python eyecare.py monitors                   # 列出显示器
python eyecare.py selftest                   # 自检（不动屏幕）
```

### 命令细节

| 命令 | 说明 |
|---|---|
| `warm [K]` | 切到色温 K，**默认同时** -15% 亮度 / -8% 对比 / -15% 蓝切 |
| `off` | 还原备份的原始 ramp；无备份则按恒等 ramp 还原 |
| `status` | 显示当前 R/G/B 总量、R/B 比、亮度、备份时间、推测匹配的预设 |
| `auto` | 读 `eyecare_config.json` 的 schedule，按时间段自动切 |
| `sunset` | 用 NOAA 算法算今天真实 sunrise/sunset，按相对时段切（高纬度异常自动 fallback 到 clock）|
| `daemon` | 启动 `auto` + `break` 两个线程并行 |
| `break` | 每 N 分钟弹一次 `MessageBoxW` 提示看远，M 分钟后点 OK |
| `preset` | 应用某个预设，可选 `--tween N` 平滑过渡秒数 |
| `rebackup` | 删除旧备份并重新保存当前 ramp 为"原始" |
| `config` | 显示当前完整配置（含 schedule、休息间隔等）|
| `monitors` | 枚举 Windows 显示器（信息查看）|
| `selftest` | 跑色彩数学、ramps、调度逻辑、sun_times 的自检，不动屏幕 |

---

## 4. 一键脚本

所有 `.bat` 都在 `D:\npy-demo\eyecare` 下。每个一键档位脚本默认带 `--tween 2` 的 2 秒平滑过渡。

### 关闭 / 还原

| 脚本 | 对应命令 |
|---|---|
| `护眼关.bat` | `off` |

### 一键档位（手动选）

| 脚本 | 预设 | 何时用 |
|---|---|---|
| `护眼-专注.bat` | focus | 白天办公室高专注时段 |
| `护眼-代码.bat` | code | 白天长时间写码 |
| `护眼-深色代码.bat` | code-dark | VS Code 等深色 IDE 主题（保对比）|
| `护眼-阅读.bat` | docs | 看文档 / 网页（白底最伤眼档）|
| `护眼-傍晚.bat` | evening | 下班后 |
| `护眼-深夜.bat` | night | 深夜 |
| `护眼开-4500K.bat` | warm 4500 | 老的"只改色温"用法，会顺带做轻度亮度/对比/蓝切保护 |

### 自动 / 后台

| 脚本 | 说明 |
|---|---|
| `自动模式.bat` | 按 clock-based 时间表自动切（一次性前台跑）|
| `守护模式.bat` | **推荐常驻**：`auto` + `break` 并行 |
| `休息提醒.bat` | 仅休息提醒循环 |
| `日落模式.bat` | 按真实日出日落切 |

---

## 5. 7 个预设

| 预设 | 色温 | 亮度 | 对比 | 蓝切 | 设计意图 |
|---|---|---|---|---|---|
| `off` | 6500K | 100% | 100% | 0% | 关闭护眼 |
| `focus` | 5800K | **92%** | 95% | 5% | 白天高专注，**匹配亮环境** |
| `code` | 5500K | 80% | 90% | 15% | 白天长时间写码 |
| `code-dark` | 6000K | 95% | **100%** | 5% | **深色主题专用**（保对比）|
| `docs` | 4700K | **60%** | **82%** | **30%** | **读白底文档**（最强保护）|
| `evening` | 4000K | 55% | 82% | 40% | 下班后启动褪黑素 |
| `night` | 3200K | **40%** | 75% | **55%** | **深夜**（极暖）|

### 几个值得记住的"为什么"

- **`code-dark` 对比度 1.0**：深色 IDE 用户**不要**叠加对比度压缩，背景已经接近黑了，再压就糊成一片
- **`docs` 亮度 60% + 蓝切 30%**：白底文档是程序员眼疲劳最大场景，给最狠的保护
- **`night` 亮度 40% + 蓝切 55%**：深夜 + 无环境光状态需要强保护，也是影响褪黑素最强时段
- **`focus` 比 `code` 温和**：因为 `focus` 设计用于明亮办公室（高环境光），屏幕必须亮些才能匹配；反例是在亮办公室用 `evening` 反而累眼

---

## 6. 守护模式详解

```powershell
python eyecare.py daemon
# 或双击 守护模式.bat
```

启动后：

```
守护模式启动（Ctrl+C 退出）：auto 平移 5s + 提醒每 20min
今日时间表：
  09:00-16:00  ->  focus   (白天高专注时段（办公室亮环境，轻度暖色）)
  16:00-18:00  ->  code    (下班前（自然光渐暗，开始暖化）)
  18:00-22:00  ->  evening (下班后（启动褪黑素）)
  22:00-09:00  ->  night   (深夜（极暖，适合无环境光）)  (跨午夜)
```

**两条线程并行**：

- **auto 线程**：每 30 秒检查一次当前小时，匹配到 schedule 的预设后用 5 秒 ease-out 三次曲线平滑过渡过去
- **break 线程**：每 5 秒检查一次 `break.interval_min` 是否到期，到期后弹模态 `MessageBoxW`，用户在看完 20 秒远景后点"确定"

`Ctrl+C` 退出后：

1. 发 `stop` 信号让两线程收尾
2. 等最多 2 秒 join
3. 还原备份的原始 ramp

---

## 7. 自动模式时间表

默认时间表（适合 9:00-18:00 上班族）：

```json
{
  "auto": {
    "tween_seconds": 5,
    "schedule": [
      {"start": 9,  "end": 16, "preset": "focus"},
      {"start": 16, "end": 18, "preset": "code"},
      {"start": 18, "end": 22, "preset": "evening"},
      {"start": 22, "end": 9,  "preset": "night"}
    ]
  }
}
```

`start` / `end` 单位是小时（0-23）。支持**跨午夜**：`start=22, end=9` 表示从 22:00 到次日 09:00。

切换是 lazy 的：`auto` 每 60 秒 check 一次当前小时，只有当**预设名变化**时才 tween。所以你随便改配置，下一次 60 秒内就会应用。

---

## 8. 休息提醒（20-20-20）

> 每 **20 分钟**，看 **20 英尺**（约 6 米）外 **20 秒**。
> —— American Academy of Ophthalmology 推荐的唯一有 RCT 证据的护眼习惯。

启动：

```powershell
python eyecare.py break
# 或双击 休息提醒.bat
```

可调参数：

```powershell
python eyecare.py break --every 30 --duration 30
```

| 配置项 | 默认 | 含义 |
|---|---|---|
| `break.interval_min` | 20 | 提醒间隔（分钟）|
| `break.duration_s` | 20 | 弹窗文案里建议的看远秒数（仅文案，不强制计时）|

弹窗是 Windows 原生 `MessageBoxW`（MB_ICONINFORMATION 蓝圈 i 图标）。点 OK 才结束弹窗 —— 你可以看着远方边点 OK。

> **开会时这个弹窗很烦**？提前 `Ctrl+C` 退掉 `break` 线程（在 `daemon` 模式里整体退也行），或者把 `interval_min` 改成 45。

---

## 9. 日落模式

```powershell
python eyecare.py sunset
# 或双击 日落模式.bat
```

跟 `auto` 的区别：用 **NOAA 太阳位置算法** 算今天**真实的** sunrise/sunset，再按相对时段切档（不是固定 19:00 切）。

### 算法概要

```
太阳赤纬(rad) = 0.006918
              - 0.399912 · cos(γ)
              + 0.070257 · sin(γ)
              - 0.006758 · cos(2γ)
              + 0.000907 · sin(2γ)
              - 0.002697 · cos(3γ)
              + 0.00148  · sin(3γ)
              其中 γ = 2π / 365 · (doy - 1)

Equation of Time (分钟) = 9.87 · sin(2B) - 7.53 · cos(B) - 1.5 · sin(B)
              其中 B = 2π / 365 · (doy - 81)

天顶角 zenith = 90.833°（含折射 + 太阳半径）

cos(HA) = (cos(zenith) - sin(lat)·sin(decl)) / (cos(lat)·cos(decl))

solar_noon_UTC = 12 - lon/15 - EOT/60   （小时）

sunrise_local = (solar_noon_UTC - HA/15 + utc_offset) mod 24
sunset_local  = (solar_noon_UTC + HA/15 + utc_offset) mod 24
```

对上海 (31.23°N, 121.47°E) 精度 ±4 分钟。

### 跨经纬度配置

```powershell
python eyecare.py sunset --lat 39.90 --lon 116.40   # 北京
```

或改 `eyecare_config.json`：

```json
{"auto": {"lat": 39.90, "lon": 116.40}}
```

### 极地 fallback

如果 `sunset - sunrise < 1` 小时（极昼 / 极夜），自动 fallback 到 clock-based 调度，不会卡死。

---

## 10. 配置（eyecare_config.json）

首次运行任何会修改屏幕的命令时自动生成（不是自动写盘，**修改配置需要手动编辑或重置**）：

```json
{
  "auto": {
    "tween_seconds": 5,
    "sunset_mode": false,
    "lat": 31.23,
    "lon": 121.47,
    "schedule": [
      {"start": 9,  "end": 16, "preset": "focus"},
      {"start": 16, "end": 18, "preset": "code"},
      {"start": 18, "end": 22, "preset": "evening"},
      {"start": 22, "end": 9,  "preset": "night"}
    ]
  },
  "break": {
    "interval_min": 20,
    "duration_s": 20
  }
}
```

### 字段说明

| 路径 | 默认 | 含义 |
|---|---|---|
| `auto.tween_seconds` | 5 | 切换档位时的平滑过渡秒数 |
| `auto.sunset_mode` | false | 暂未启用，预留给"auto mode 也用 sun_times" |
| `auto.lat` | 31.23 | 日落算法的纬度 |
| `auto.lon` | 121.47 | 日落算法的经度 |
| `auto.schedule` | 见上 | 时间表 |
| `break.interval_min` | 20 | 提醒间隔分钟 |
| `break.duration_s` | 20 | 弹窗里建议的看远秒数（仅文案）|

### 改完重启

`auto` / `daemon` 是常驻循环，改完配置需要 `Ctrl+C` 退出再启动。

---

## 11. 工作原理

### Windows GDI Gamma Ramp

屏幕最终送出的颜色 = 操作系统渲染颜色 → 应用 gamma ramp → 显示器。

```
   OS rendered      gamma ramp         最终显示
   RGB value        (per-channel)      RGB
   ─────────────    ──────────────     ─────────────
        0      →    ramp[0]    =    0
        1      →    ramp[1]    =    ?
        ...
        255    →    ramp[255]  =    65535
```

我们通过 `SetDeviceGammaRamp` 修改这 768 个 16-bit 值（R, G, B 各 256 个），就改变最终显示的颜色。

### 4 个独立维度的合成

```python
def build_ramp_from_params(kelvin, brightness, contrast, blue_cut):
    ramp = identity_ramp()                              # 100% baseline
    ramp = apply_contrast(ramp, contrast)               # 拉低对比
    ramp = apply_brightness(ramp, brightness)           # 整体缩放
    mr, mg, mb = kelvin_to_multipliers(kelvin)          # 暖色 (R=1, G<1, B<<1)
    mb *= (1 - blue_cut)                                # 再单独砍一刀 B
    return apply_tint(ramp, mr, mg, mb)
```

- **`identity_ramp()`**：`ramp[i] = i*257`，相当于"什么都不做"
- **`contrast 0.85`**：`out = mid + (v - mid) * 0.85`，把"远离中间灰"的距离压短，画面颜色不那么极端
- **`brightness 0.80`**：每个值 ×0.8，整体变暗，颜色比例不变
- **`kelvin tint`**：根据目标色温算出 (R, G, B) 三个乘子（暖色 = R 高 G 中 B 低）
- **`blue_cut`**：在 B 通道再额外砍一刀（标准 Kelvin 切暖不够，要多切点）

### 平滑过渡（tween）

```python
eased = 1 - (1 - t) ** 3   # ease-out cubic
ramp = from + (to - from) * eased
```

每 1/30 秒写一次 ramp。5 秒共 150 帧。ease-out 三次曲线让开始变化快、结尾变化慢，给眼睛"安静变完"的感觉。

### 备份

第一次跑任何会改屏的命令时：

```python
if not original_ramp.json.exists():
    original_ramp.json.write(json.dumps(read_ramp()))
```

之后 `off` 就还原它。如果你后来换了显示器色彩配置文件，跑 `rebackup` 重新生成基线。

---

## 12. 调参建议

### 亮度档位的逻辑

屏幕亮度应该匹配**环境光**：

| 环境 | 推荐屏幕亮度乘子 |
|---|---|
| 强日光直射 / 户外 | 100%+ |
| 明亮办公室（300-500 lux）| 90-95% |
| 客厅灯下（150 lux）| 70-85% |
| 关灯看电视（<50 lux）| 50-65% |
| 深夜全黑 | 30-50% |

> **反例**：在亮办公室里把屏幕调到 50%（用 `evening` 档），会因为"屏幕是视野里最暗的东西"让眼睛疲劳 —— 这是 v1 时代常见的误区。
> 这就是为什么 `focus`（白天的预设）只有 92% 而不是 70%：它是为亮办公室设计的。

### 程序员一天的最佳实践

| 时段 | 建议 |
|---|---|
| 上午 9-12 高峰专注 | `focus` 或 `off` —— 蓝光帮你清醒，开太狠反而困 |
| 下午 14-16 疲劳期 | `code` |
| 下班前 16-18 自然光落 | 切到 `code` 或起 `daemon` |
| 下班后 18-22 | `evening` |
| 深夜 22 后 | `night`（如果要加班）|

进阶：

1. **白天别开太狠**：在亮办公室 9-12 点，用 `focus` 或 `off`，保留自然蓝光帮助保持警觉
2. **下午开**：16 点后太阳光下降，用 `code` 或 `daemon`
3. **夜班开狠**：22 点后无环境光，用 `night`
4. **读完文档后走远看**：`docs` 档不能取代 20-20-20
5. **IDE 主题**：深色主题用 `code-dark`，保对比；浅色主题用 `code`，降对比减少睫状肌压力

### 临时自定义色温

```powershell
python eyecare.py warm 3800     # 3800K（白炽灯泡感）
python eyecare.py warm 5200     # 5200K
```

### 长期持有自定义档

直接编辑 `eyecare_config.json` 里加一条 schedule 条目，或者改 `eyecare.py` 里的 `PRESETS` dict。

---

## 13. 故障排除

### "写入失败：驱动可能不支持或当前有全屏独占应用"

常见原因：

- 显卡驱动在 HDR / 游戏模式 / 全屏独占应用中拒绝 gamma ramp
- 解决方法：关掉全屏 app，或者把驱动设置为"标准颜色模式"
- 笔记本 + 集显切换可能也会触发，锁定独显后再试

### 屏幕没变化 / 变了但切不回去

```powershell
python eyecare.py status       # 看 ramp 数值
python eyecare.py selftest     # 自检
# 看 original_ramp.json 文件还在不在；不在了：
python eyecare.py rebackup
```

### 显示器色彩配置文件冲突

Windows 可能同时应用多个 gamma 调整（夜间灯光、本工具、外置滤镜）造成冲突。**建议二选一**：本工具 vs Windows 夜间灯光，不要同时开。

### 状态里"R/B 比"看着不对

正常范围参考：

| R/B 比 | 状态 |
|---|---|
| 0.95 - 1.05 | 标准 6500K |
| 1.05 - 1.15 | focus / 微暖 |
| 1.15 - 1.30 | code / evening |
| 1.30 - 1.50 | night |
| > 1.50 | 极暖（可能多个工具叠加）|

### 多显示器

- 当前只对"桌面"整体 HDC 应用 —— 所有显示器**同样**变色
- per-monitor 颜色需要枚举 `EnumDisplayDevices` 后给每个 `CreateDC`，**当前未支持**
- 如果你有一台**用于校色的**显示器，不要在调色后用它对比

### 备份丢了 / 想强制重置

```powershell
del original_ramp.json
python eyecare.py rebackup
```

### Python 版本不对

报错 `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`？说明 Python < 3.10。升级到 3.10+ 即可。

---

## 14. 文件清单

```
D:\npy-demo\eyecare\
├── eyecare.py                主程序（~600 行，单文件无依赖）
├── README.md                 本文档
├── eyecare_config.json       运行后生成：自动配置 + 用户自定义
├── original_ramp.json        首次调色时生成：备份原始 gamma ramp（768 个 int）
├── nightlight_backup.json    Windows 自带夜间灯的备份（与本工具无关）
│
├── 护眼关.bat                off
├── 护眼开-4500K.bat          warm 4500（兼容老用法）
├── 自动模式.bat              auto --tween 5
├── 守护模式.bat              daemon
├── 休息提醒.bat              break --every 20
├── 日落模式.bat              sunset
│
├── 护眼-专注.bat             preset focus
├── 护眼-代码.bat             preset code
├── 护眼-深色代码.bat         preset code-dark
├── 护眼-阅读.bat             preset docs
├── 护眼-傍晚.bat             preset evening
└── 护眼-深夜.bat             preset night
```

### 关键技术指标

- **0 依赖**：仅 `ctypes` / `json` / `math` / `argparse` / `threading`
- **二进制 footprint**：1 个 `.py` 文件（约 30KB）
- **屏幕 ramp 写入开销**：~1ms / 次
- **tween 帧率**：30 fps（5 秒 150 帧）
- **日落算法精度**：±4 分钟（NOAA + EOT）
- **完全离线**：不联网、不上传任何数据

---

最后更新：2026-10 · v2