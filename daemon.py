"""bsk daemon 管理：状态查询、启动、停止。

管理 BrowserSkill（bsk）的本地 daemon。daemon 是让浏览器扩展连接、
复用已登录浏览器会话的后台服务。
"""

import json
import os
import shutil
import subprocess

# daemon 数据目录（优先读环境变量，其次用用户默认安装位置）
BSK_HOME = os.environ.get("BSK_HOME", r"E:\DevTools\bsk\home")

# bsk 可执行文件的候选路径（按优先级）
_BSK_CANDIDATES = [
    r"E:\DevTools\bsk\bsk.exe",
    r"C:\Users\Administrator\.local\bin\bsk.exe",
]


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


def _env() -> dict:
    """构造带 BSK_HOME 与 BSK_AUTO_START=0 的子进程环境。

    BSK_AUTO_START=0 避免 status 等查询命令在 daemon 未运行时隐式拉起新 daemon，
    这样「未启动」状态能被如实反映。
    """
    env = os.environ.copy()
    env["BSK_HOME"] = BSK_HOME
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
            env=_env(),
            timeout=5,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            if data.get("daemon_version"):
                return True, data
            return False, data
        return False, {"error": (r.stderr or r.stdout).strip()}
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
        return False, {"error": str(e)}


def start():
    """启动 daemon（后台独立运行，不阻塞）。

    返回 (ok, message)。
    """
    try:
        r = subprocess.run(
            [_find_bsk(), "daemon", "start"],
            capture_output=True,
            text=True,
            env=_env(),
            timeout=30,
        )
        msg = (r.stdout or r.stderr).strip()
        return r.returncode == 0, msg
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)


def stop():
    """停止 daemon。

    返回 (ok, message)。
    """
    try:
        r = subprocess.run(
            [_find_bsk(), "daemon", "stop"],
            capture_output=True,
            text=True,
            env=_env(),
            timeout=30,
        )
        msg = (r.stdout or r.stderr).strip()
        return r.returncode == 0, msg
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
