"""bsk daemon 管理：状态查询、启动、停止。

管理 BrowserSkill（bsk）的本地 daemon。daemon 是让浏览器扩展连接、
复用已登录浏览器会话的后台服务。

启动策略（适配 bsk 0.3.1+）：
  0.3.1 起 `bsk daemon start` 的后台 breakaway 模式在部分 Windows 环境（受
  Job Object / 安全软件限制）会报「拒绝访问 (os error 5)」而失败。因此采用两级策略：
    1) 先试标准独立启动（daemon 完全独立，不依赖本程序存活）；
    2) 若失败，回退到 `--foreground` 受管模式，由本程序持有 daemon 子进程。
  该回退不依赖 breakaway 权限，在受限环境下仍可用。

所有对 bsk 的子进程调用都带 CREATE_NO_WINDOW，避免弹出黑框。
"""

import json
import os
import shutil
import subprocess

# daemon 数据目录（优先读环境变量，其次用用户默认安装位置）
BSK_HOME = os.environ.get("BSK_HOME", r"E:\DevTools\bsk\home")

# Windows 上隐藏子进程控制台窗口的标志
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# bsk 可执行文件的候选路径（按优先级）
_BSK_CANDIDATES = [
    r"E:\DevTools\bsk\bsk.exe",
    r"C:\Users\Administrator\.local\bin\bsk.exe",
]

# 受管模式下持有的 foreground daemon 子进程句柄（必须保留引用，否则被回收）
_daemon_proc = None


def _find_bsk() -> str:
    """定位 bsk 可执行文件：优先 PATH，其次候选绝对路径。"""
    found = shutil.which("bsk")
    if found:
        return found
    for p in _BSK_CANDIDATES:
        if os.path.exists(p):
            return p
    # 兜底：让 subprocess 在 PATH 里自行解析，失败时抛出可读错误
    return "bsk"


def _base_env() -> dict:
    """基础子进程环境：带上 BSK_HOME（daemon 与查询命令必须指向同一目录）。"""
    env = os.environ.copy()
    env["BSK_HOME"] = BSK_HOME
    return env


def _query_env() -> dict:
    """查询用环境：额外禁用隐式自动启动，保证「未启动」状态被如实反映。"""
    env = _base_env()
    env["BSK_AUTO_START"] = "0"
    return env


def status():
    """查询 daemon 状态。

    返回 (running, info)：
      - running: bool，daemon 是否在运行
      - info:    dict，daemon 的 JSON 状态（如 pid、browsers 等）；失败时为错误信息
    """
    try:
        r = subprocess.run(
            [_find_bsk(), "status", "--json"],
            capture_output=True,
            text=True,
            env=_query_env(),
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            if data.get("daemon_version"):
                return True, data
            return False, data
        # 非 0 返回：优先解析 JSON 里的 message 作为可读错误
        try:
            data = json.loads(r.stdout)
            return False, {
                "error": data.get("message", ""),
                "exit_code": data.get("exit_code"),
            }
        except json.JSONDecodeError:
            return False, {"error": (r.stderr or r.stdout).strip()}
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
        return False, {"error": str(e)}


def start():
    """一级启动：以独立进程方式触发 daemon（breakaway），立即返回。

    成功时 daemon 完全独立于本程序。启动结果需由调用方随后用 status() 确认
    （daemon 初始化需要一点时间）。

    返回 (ok, message)：ok 仅表示「命令已下发」，不代表 daemon 已就绪。
    """
    running, _ = status()
    if running:
        return True, ""

    try:
        subprocess.Popen(
            [_find_bsk(), "daemon", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_base_env(),
            creationflags=CREATE_NO_WINDOW,
        )
        return True, ""
    except OSError as e:
        return False, str(e)


def start_supervised():
    """二级启动（回退）：以 --foreground 模式作为本程序子进程持有 daemon。

    不依赖 breakaway 权限，用于一级启动失败的环境。

    返回 (ok, message)。
    """
    global _daemon_proc

    running, _ = status()
    if running:
        return True, ""

    # 旧句柄若已退出则清空
    if _daemon_proc is not None and _daemon_proc.poll() is not None:
        _daemon_proc = None

    try:
        _daemon_proc = subprocess.Popen(
            [_find_bsk(), "daemon", "start", "--foreground"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_base_env(),
            creationflags=CREATE_NO_WINDOW,
        )
        return True, ""
    except OSError as e:
        return False, str(e)


def has_supervised_daemon() -> bool:
    """本程序是否正持有受管（foreground）daemon 子进程。"""
    return _daemon_proc is not None and _daemon_proc.poll() is None


def stop():
    """停止 daemon。

    先用 `bsk daemon stop` 优雅停止；若受管模式下持有的子进程仍未退出，
    再直接终止它，确保不留残留。

    返回 (ok, message)。
    """
    global _daemon_proc

    ok, msg = False, ""
    try:
        r = subprocess.run(
            [_find_bsk(), "daemon", "stop"],
            capture_output=True,
            text=True,
            env=_query_env(),
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        msg = (r.stdout or r.stderr).strip()
        ok = r.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        msg = str(e)

    # 兜底：受管子进程若仍在运行，直接终止
    if _daemon_proc is not None and _daemon_proc.poll() is None:
        try:
            _daemon_proc.terminate()
            _daemon_proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                _daemon_proc.kill()
                _daemon_proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
    _daemon_proc = None

    return ok, msg
