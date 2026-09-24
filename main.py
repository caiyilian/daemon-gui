"""daemon-gui：bsk daemon 的托盘守护界面。

功能：
  - 最小化到系统托盘
  - 显示 daemon「已启动 / 未启动」状态
  - 启动 / 停止 daemon
  - 开机自启开关（写入 Windows 注册表 HKCU Run 键）
"""

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import autostart
import daemon

REFRESH_MS = 5000  # 状态刷新间隔（毫秒）


def _build_icons():
    """预生成两个托盘图标：绿点=运行，灰点=停止。"""

    def dot(color):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(10, 10, 44, 44)
        p.end()
        return QIcon(pm)

    return {"running": dot("#1D9E75"), "stopped": dot("#888780")}


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Daemon 服务管理")
        self.resize(340, 170)

        self.status_label = QLabel("状态：未知")
        self.status_label.setStyleSheet("font-size: 17px;")

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color: #888;")
        self.detail_label.setWordWrap(True)

        self.start_btn = QPushButton("开启服务")
        self.stop_btn = QPushButton("停止服务")

        self.autostart_cb = QCheckBox("开机自启")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.detail_label)
        layout.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(self.autostart_cb)
        self.setLayout(layout)

        self.start_btn.clicked.connect(self.on_start)
        self.stop_btn.clicked.connect(self.on_stop)
        self.autostart_cb.toggled.connect(self.on_autostart_toggled)

    def closeEvent(self, event):
        # 关闭窗口 = 隐藏到托盘，不退出程序
        event.ignore()
        self.hide()

    def on_start(self):
        ok, msg = daemon.start()
        if not ok and msg:
            self.detail_label.setText(f"开启失败：{msg[:120]}")
            return
        self.detail_label.setText("正在开启服务…")
        self._start_retry = 0
        self._supervised = False
        QTimer.singleShot(1500, self._refresh_after_start)

    def _refresh_after_start(self):
        """启动后确认状态；daemon 初始化需要时间，最多重试 3 次。"""
        running, info = daemon.status()
        if running:
            self.apply_state(running, info)
            return

        self._start_retry += 1
        if self._start_retry < 3:
            QTimer.singleShot(2000, self._refresh_after_start)
            return

        # 一级启动（独立进程）失败 → 回退到受管 foreground 模式
        if not self._supervised:
            self._supervised = True
            ok, msg = daemon.start_supervised()
            if not ok and msg:
                self.detail_label.setText(f"开启失败：{msg[:120]}")
                return
            self.detail_label.setText("正在以受管模式开启服务…")
            self._start_retry = 0
            QTimer.singleShot(2000, self._refresh_after_start)
            return

        # 两级都失败
        self.apply_state(False, info)

    def on_stop(self):
        ok, msg = daemon.stop()
        if not ok and msg:
            self.detail_label.setText(f"停止失败：{msg[:120]}")
        self.apply_state(*daemon.status())

    def on_autostart_toggled(self, checked):
        autostart.set_enabled(checked)

    def apply_state(self, running, info):
        self.status_label.setText("状态：已启动" if running else "状态：未启动")
        if running and isinstance(info, dict):
            pid = info.get("pid", "?")
            browsers = info.get("browsers", [])
            self.detail_label.setText(f"daemon pid {pid} · 已连接浏览器 {len(browsers)}")
        else:
            self.detail_label.setText("服务未运行，点击「开启服务」启动")
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)


class TrayApp:
    def __init__(self, app: QApplication, window: MainWindow):
        self.app = app
        self.window = window
        self.running = False
        self.icons = _build_icons()

        self.tray = QSystemTrayIcon(self.icons["stopped"], app)
        self.tray.setToolTip("Daemon GUI")

        self.menu = QMenu()
        self.status_action = QAction("状态：未启动")
        self.status_action.setEnabled(False)
        self.start_action = QAction("开启服务")
        self.stop_action = QAction("停止服务")
        self.autostart_action = QAction("开机自启")
        self.autostart_action.setCheckable(True)
        self.show_action = QAction("打开界面")
        self.quit_action = QAction("退出")

        self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        self.menu.addAction(self.start_action)
        self.menu.addAction(self.stop_action)
        self.menu.addSeparator()
        self.menu.addAction(self.autostart_action)
        self.menu.addAction(self.show_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_activated)

        self.start_action.triggered.connect(self.window.on_start)
        self.stop_action.triggered.connect(self.window.on_stop)
        self.autostart_action.toggled.connect(self.on_autostart_toggled)
        self.show_action.triggered.connect(self.show_window)
        self.quit_action.triggered.connect(self.quit)

        self.tray.show()

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)

        # 同步初始自启状态
        enabled = autostart.is_enabled()
        self.autostart_action.setChecked(enabled)
        self.window.autostart_cb.setChecked(enabled)

        # 启动时确保 daemon 运行（守护语义）
        self.refresh()
        if not self.running:
            self.window.on_start()

    def on_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def on_autostart_toggled(self, checked):
        autostart.set_enabled(checked)
        self.window.autostart_cb.blockSignals(True)
        self.window.autostart_cb.setChecked(checked)
        self.window.autostart_cb.blockSignals(False)

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def refresh(self):
        running, info = daemon.status()
        self.running = running
        self.tray.setIcon(self.icons["running" if running else "stopped"])
        self.tray.setToolTip("Daemon GUI — 已启动" if running else "Daemon GUI — 未启动")
        self.status_action.setText("状态：已启动" if running else "状态：未启动")
        self.start_action.setEnabled(not running)
        self.stop_action.setEnabled(running)
        self.window.apply_state(running, info)

    def quit(self):
        # 仅当 daemon 是本程序以受管（foreground）模式持有的时候，退出时才一并停掉；
        # 独立进程模式的 daemon 可自行存活，退出 GUI 不影响它。
        if daemon.has_supervised_daemon():
            try:
                daemon.stop()
            except Exception:
                pass
        self.tray.hide()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    tray = TrayApp(app, window)  # 必须保存引用，否则实例被 GC、托盘信号槽全部失效

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
