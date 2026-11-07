# -*- coding: utf-8 -*-
"""任务子进程管理：桌面面板的投递任务执行器。"""
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import dotenv_values

BASE_DIR = Path(__file__).parent


# ================= 任务进程管理 =================
class TaskRunner:
    """子进程管理：所有输出只进队列，由界面线程轮询消费。"""

    def __init__(self):
        self.proc = None
        self.log_queue = queue.Queue()
        self.started_at = None
        self.exit_code = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> str:
        if self.running():
            return "任务已在运行中"
        env = os.environ.copy()
        env.update({
            key: value
            for key, value in dotenv_values(BASE_DIR / ".env").items()
            if key and value is not None
        })
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        self.log_queue = queue.Queue()
        self.exit_code = None
        self.started_at = time.time()
        self.log_queue.put(f"[面板] {time.strftime('%H:%M:%S')} 启动任务 auto_deliver.py")
        self.proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "auto_deliver.py")],
            cwd=str(BASE_DIR), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        threading.Thread(target=self._pump, daemon=True).start()
        return "已启动"

    def stop(self) -> str:
        if not self.running():
            return "当前没有运行中的任务"
        proc = self.proc
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        except Exception:
            proc.kill()
        self.log_queue.put(f"[面板] {time.strftime('%H:%M:%S')} 任务已手动停止")
        return "已停止"

    def _pump(self):
        proc = self.proc
        for line in proc.stdout:
            self.log_queue.put(line.rstrip("\n"))
        code = proc.wait()
        self.exit_code = code
        self.log_queue.put(f"[面板] {time.strftime('%H:%M:%S')} 任务结束，退出码 {code}")


