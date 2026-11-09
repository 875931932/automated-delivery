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

from app_paths import get_app_dir, get_data_dir, is_frozen
from process_runtime import quiet_process_options, worker_python

BASE_DIR = get_data_dir()
APP_DIR = get_app_dir()


def format_exit_status(exit_code, manually_stopped=False) -> str:
    if exit_code is None:
        return "空闲"
    if manually_stopped:
        return f"任务已手动停止（退出码 {exit_code}）"
    if exit_code == 0:
        return "任务正常结束（退出码 0）"
    if exit_code == 130:
        return "任务被中断（退出码 130）"
    return f"任务运行失败（退出码 {exit_code}）"


# ================= 任务进程管理 =================
class TaskRunner:
    """子进程管理：所有输出只进队列，由界面线程轮询消费。"""

    def __init__(self):
        self.proc = None
        self.log_queue = queue.Queue()
        self.started_at = None
        self.exit_code = None
        self.stop_requested = False

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> str:
        if self.running():
            return "任务已在运行中"
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env_values = dotenv_values(BASE_DIR / ".env")
        raw_env_values = dotenv_values(BASE_DIR / ".env", interpolate=False)
        if "GREETING_PROMPT" in raw_env_values:
            env_values["GREETING_PROMPT"] = raw_env_values["GREETING_PROMPT"]
        env.update({
            key: value for key, value in env_values.items()
            if key and value is not None
        })
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        self.log_queue = queue.Queue()
        self.exit_code = None
        self.stop_requested = False
        self.started_at = time.time()
        if is_frozen():
            worker = APP_DIR / "auto_deliver_worker.exe"
            if not worker.is_file():
                return f"缺少任务运行文件：{worker}"
            command = [str(worker)]
            task_name = worker.name
        else:
            command = [worker_python(), str(APP_DIR / "auto_deliver.py")]
            task_name = "auto_deliver.py"

        self.log_queue.put(
            f"[面板] {time.strftime('%H:%M:%S')} 启动任务 {task_name}"
        )
        try:
            self.proc = subprocess.Popen(
                command,
                cwd=str(BASE_DIR), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                **quiet_process_options(),
            )
        except OSError as exc:
            self.proc = None
            return f"任务进程启动失败：{exc}"
        threading.Thread(target=self._pump, daemon=True).start()
        return "已启动"

    def stop(self) -> str:
        if not self.running():
            return "当前没有运行中的任务"
        proc = self.proc
        self.stop_requested = True
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=15, **quiet_process_options())
        except Exception:
            proc.kill()
        self.log_queue.put(f"[面板] {time.strftime('%H:%M:%S')} 已请求手动停止")
        return "已停止"

    def _pump(self):
        proc = self.proc
        for line in proc.stdout:
            self.log_queue.put(line.rstrip("\n"))
        code = proc.wait()
        self.exit_code = code
        status = format_exit_status(code, self.stop_requested)
        self.log_queue.put(f"[面板] {time.strftime('%H:%M:%S')} {status}")


