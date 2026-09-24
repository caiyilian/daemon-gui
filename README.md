# daemon-gui

一个 Windows 系统托盘小工具，用于守护 [BrowserSkill](https://github.com/Tencent/BrowserSkill)（`bsk`）的本地 daemon，让浏览器扩展随时能连上、复用你已登录的浏览器会话。

## 功能

- **托盘常驻**：关闭窗口即最小化到系统托盘，不退出程序。
- **状态显示**：托盘图标 + 主窗口实时显示 daemon「已启动 / 未启动」，并显示 pid 与已连接浏览器数。
- **启动 / 停止**：一键启动或停止 `bsk daemon`。
- **开机自启**：勾选后写入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，开机自动拉起本程序并自动启动 daemon。

## 依赖

- Python 3.9+
- PySide6

```bash
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

程序启动后会：
1. 检查 `bsk daemon` 状态；
2. 若未运行，自动启动它；
3. 显示主窗口，关闭窗口则缩到托盘（每 5 秒刷新一次状态）。

## 打包成 exe（可选）

```bash
pip install pyinstaller
pyinstaller -F -w -n DaemonGUI main.py
```

打包后 `autostart.py` 会识别 `sys.frozen`，开机自启直接指向 exe（不再依赖 Python 环境）。

## 开机自启原理

- 开启：在 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下写入 `DaemonGUI` 键，值为启动本程序的命令。
- 关闭：删除该键。
- 脚本运行时用 `pythonw.exe`（无黑框）；打包成 exe 后直接运行 exe。

## 项目结构

```
daemon-gui/
├── main.py          # 入口 + 托盘 GUI 逻辑
├── daemon.py        # bsk daemon 状态查询 / 启动 / 停止
├── autostart.py     # 开机自启（注册表读写）
├── requirements.txt
└── README.md
```

## 环境约定

- `bsk` 可执行文件：优先从 PATH 查找，其次 `~/.local/bin/bsk.exe`（按当前用户动态解析）、`E:\DevTools\bsk\bsk.exe`、`C:\Users\Administrator\.local\bin\bsk.exe`。
- daemon 数据目录 `BSK_HOME`：仅在环境变量显式设置时覆盖，否则交给 bsk 走默认（`~/.bsk`）。
- 状态查询始终带 `BSK_AUTO_START=0`，避免查询时隐式拉起 daemon 导致「未启动」被误判。

## 启动策略（适配 bsk 0.3.1+）

bsk 0.3.1 起，`bsk daemon start` 的后台 breakaway 模式在部分 Windows 环境（受 Job Object 或安全软件限制）会报「拒绝访问 (os error 5)」而失败。为此本工具采用**两级启动**：

1. **一级：独立进程启动** —— 先尝试标准 `bsk daemon start`，成功则 daemon 完全独立，关闭本程序也不影响它；
2. **二级：受管模式回退** —— 一级失败时，自动改用 `bsk daemon start --foreground`，由本程序持有 daemon 子进程。该方式不依赖 breakaway 权限，受限环境下仍可用。

> 注意：受管模式下 daemon 依附于本程序，**退出程序会一并停止服务**；独立模式下退出程序不影响 daemon。程序会按实际情况自动选择，无需手动干预。
