# Linux/XWayland 桌面背景拖拽修复

> 基线：`34d810b1eadd98d00e7cb9b3b51428a45b5bf03e`；日期：2026-10-26。
> 已在 Linux v4.4.0 安装包中验证，并由用户确认桌面背景上已能正常拖动。

## 一、核心特性

用户反馈：桌宠位于应用窗口上时有时能交互，但位于 GNOME/Wayland 的桌面背景上拖不动。
旧实现按 `QCursor.pos()` 的当前结果反复切换整张 overlay 的输入穿透。如果 XWayland
位置查询滞留在透明区域，整张窗会保持穿透，随后到达角色上的点击也无法进入。

新实现仅在 Linux 的 `xcb` 后端启用：通过 XFixes ShapeInput 发布角色当前轮廓，
让合成器直接路由点击，不依赖查询光标是否已进入角色。Qt 视觉窗口不裁剪；其余后端、
缺少 XFixes 的环境继续走原实现。未新增设置键。

注意证据边界：本轮没有采样用户桌面上 XQueryPointer 的真实时序。确定性复现使用
固定在透明区域的 QCursor 替身，但鼠标注入、命中、拖动与穿透均通过真实 X11 服务完成。
用户报告的原始症状与修复后的人工验收分别作为现场证据。

## 二、修改文件说明

| 文件 | 增删 | 修改及理由 |
| --- | --- | --- |
| `pet/platform_passthrough.py` | +31 / -0 | xcb 优先使用 native shape；保留原平台回退、显示后对账与拖拽收尾。 |
| `pet/x11_input_shape.py` | 新增 | 角色渲染 alpha≥16 转为物理像素输入区域；只修改 ShapeInput；一角色一份缓存与一个窗口一条 X 连接。 |
| `tests/test_x11_input_shape.py` | 新增 | 固定光标查询回归、alpha 阈值、位移、旋转、DPR、隐藏、手动穿透、拖拽与未变掩码不重写。 |
| `scripts/probe_x11_input_shape.py` | 新增 | 隔离 X11 下经 XTest 验证事件真正送达角色或背景，支持原实现对照。 |
| `scripts/benchmark_x11_input_shape.py` | 新增 | 可重复的缓存/新帧输入区域耗时基准。 |
| 本报告、`docs/INDEX.md` | 新增 / +1 | 记录验证范围、失败与未覆盖项。 |

未修改用户配置、动画素材、AI 接口或各平台构建脚本。安装包已有 `libX11.so.6`、
`libXfixes.so.3` 和 NumPy；源码中静态导入新模块，未增加 Python 运行时依赖。

## 三、实现要点

- 对角色局部画布调用既有 `sprite.paint()`，因此沿用镜像、旋转、Q 弹与缩放。
- alpha≥16 按既有点击阈值转为 1-bit mask，扫描行补齐至 32-bit，避免 QBitmap 读取错行。
- 输入区域按窗口 DPR 转为 X11 物理坐标，不把 Qt 逻辑坐标直接交给 XFixes。
- 缓存每只角色最新的本地轮廓，整数位移只平移区域；帧、DPR、姿态、亚像素落点改变才重算。
- 手动穿透发布空区域；抓取期间发布整窗输入区域，松手立即恢复轮廓；隐藏角色不参与。
- 原生窗口 ID 改变与 show 后强制重放区域；未改变的区域不重复提交。连接随 Qt 宿主销毁关闭。

## 四、性能分析

环境：Ubuntu 26.04.1 x86_64；基准 Python 3.14.4 / PySide6 6.11.2，offscreen；
1000 次采样，320×240 逻辑像素、DPR=2、实际像素 640×480。

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python scripts/benchmark_x11_input_shape.py
```

| 指标 | 本机实测均值 |
| --- | --- |
| 复用输入轮廓 | 29.52 µs / 次 |
| 新帧轮廓（含复制图片并生成 pixmap） | 6263.04 µs / 次 |

数字是合成负载、不是用户动画帧率或 CPU 保证。新增路径比旧的单点 alpha 查询更贵，
换取桌面背景上可可靠进入的原生输入区域。重算随动画帧/姿态变化，轮询仍沿用 10ms
与拖拽 100ms 档位；实际不变化的 mask 不写 X11。

新增一条每窗持有的 X 连接，区域变化时创建/设置/销毁服务器 region 并 flush；
不新增网络服务、磁盘写入或线程。每只角色最多缓存一个本地 QRegion，借助弱引用随角色
释放；新帧绘制与 NumPy 数组为角色大小的临时内存，没有整屏 framebuffer 或历史帧缓存。

## 五、实机运行记录

### 原实现与修复实现对照

使用本机运行的 Xvfb（1280×800，非 mock X 服务）与 XTest，光标查询固定在透明区域。
可选开发依赖为 `python-xlib`，不加入生产依赖。

```bash
xvfb-run -a env QT_QPA_PLATFORM=xcb QT_SCALE_FACTOR=1 PYTHONPATH=. \
  python scripts/probe_x11_input_shape.py
xvfb-run -a env QT_QPA_PLATFORM=xcb QT_SCALE_FACTOR=2 PYTHONPATH=. \
  python scripts/probe_x11_input_shape.py
```

- 原实现：`native_shape_rectangles=0`，背景可接收点击，角色点击、拖动、恢复均失败。
- 修复实现：DPR=1 和 DPR=2 的透明区域穿透、角色点击、拖动、手动穿透及恢复、hide/show
  恢复全部通过；DPR=2 时 sprite.x 从 50 移到 110。
- offscreen 固定光标回归同样先红后绿：原实现不会更新 native input shape。

### 冻结包与真实桌面

保留用户已安装 v4.4.0 的运行库、素材和配置，仅替换 `pet.platform_passthrough` 并加入
`pet.x11_input_shape` 的 Python 3.11 字节码。1976 个其他 Python 模块的压缩内容逐一
核对未变。临时测试变体只为隔离配置，未把测试设置写到用户的正式数据目录。

- 使用包内 Python 3.11.17 编译；冻结包在 Xvfb 中出现真实角色输入轮廓（226 个矩形）。
- XTest 按下使抓取区域扩为整窗；释放恢复轮廓；实际角色轮廓左边界从 631 移到 513，
  与约 120px 向左拖动一致。
- 正式程序备份后替换并重启，在 GNOME/Wayland 下仍加载 xcb 后端。真实桌面 overlay
  大小 3714×2096，读回输入区域 451 个矩形、面积 78517，而不是整屏或空区域。
- 新进程启动抽查没有 Traceback、native-shape fallback、BadWindow 或穿透更新错误。
- 用户人工验收原话：“已经能正常拖动”。此项覆盖原先失败的桌面背景场景。

真实 GNOME 下的 XTest 自动化曾因合成器坐标/时序不一致失败，未作为成功证据；
本机自动路由验证采用隔离 X11，真实桌面的最终拖拽结论采用用户人工确认。

## 六、测试与验证

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q \
  tests/test_x11_input_shape.py tests/test_platform_passthrough.py \
  tests/test_overlay_window.py tests/test_overlay_window_capabilities.py \
  tests/test_overlay_hardening.py tests/test_sprite_dpr.py tests/test_architecture.py
```

- 相关回归：**146 passed, 2 skipped**。
- 修改文件 ruff 与 `git diff --check`：通过。
- 项目全量测试已尝试，但当前稀疏 checkout 缺少角色素材，出现既有失败；大约 1100 条
  测试标记后停止，不声称全量通过。单独复查前三个失败，均为
  `assets/characters/shenshen/videos` 缺失的 FileNotFoundError。
- 未向上游推送或合并；此分支保留源代码修复及可重复验证入口。

## 七、已知限制与后续

- 完整素材 checkout 下的全量套件、长期多宠/多显示器压力与原生 Wayland Qt 后端未验。
- 原生输入改动仅针对 Linux xcb；Windows/macOS 仍由原平台实现负责。
- 模型/API 配置与桌宠输入无关，不需要为了恢复拖拽重新填写 API Key。

相关：[初始穿透修复历史](PR-REPORT-CURSOR-PASSTHROUGH-2026-10-15.md)、
[打包说明](ONEDIR_PACKAGING.md)、[文档索引](INDEX.md)。
