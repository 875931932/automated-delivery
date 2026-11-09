# -*- coding: utf-8 -*-
"""每日投递计数（持久化）。"""
import os
import json
from datetime import date


# ========================= 每日投递计数（持久化） =========================
class DeliveryTracker:
    def __init__(self, log_file: str):
        self.log_file = log_file
        self.today = date.today().isoformat()
        self.data = {"date": self.today, "count": 0, "delivered": {}}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if saved.get("date") == self.today:
                    self.data = saved
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self):
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"[记录] 日志写入失败: {exc}")

    def can_deliver(self, daily_limit: int) -> bool:
        return self.data["count"] < daily_limit

    def mark(self, job_id: str, job_name: str, greeting: str, status: str,
             *, count_delivery: bool = True):
        if count_delivery:
            self.data["count"] += 1
        self.data["delivered"][job_id] = {
            "name": job_name, "greeting": greeting, "status": status,
        }
        self._save()

    def already_done(self, job_id: str) -> bool:
        return job_id in self.data["delivered"]
