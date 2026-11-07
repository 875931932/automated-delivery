# -*- coding: utf-8 -*-
"""平台职位类型筛选与队列优先性质之间的共享策略。"""

JOB_TYPE_PREFERENCES = ("实习", "全职")


def effective_job_type_preference(platform_job_type, job_type_preference):
    """返回实际生效的队列偏好；兼职筛选时实习/全职偏好不适用。"""
    platform_type = str(platform_job_type or "不限").strip()
    if platform_type in JOB_TYPE_PREFERENCES:
        return platform_type
    if platform_type == "兼职":
        return None

    preference = str(job_type_preference or "").strip()
    return preference if preference in JOB_TYPE_PREFERENCES else "实习"


def normalize_job_type_preference(platform_job_type, job_type_preference):
    """规范化持久化值，避免平台指定实习/全职时写入冲突偏好。"""
    effective = effective_job_type_preference(platform_job_type, job_type_preference)
    if effective is not None:
        return effective

    preference = str(job_type_preference or "").strip()
    return preference if preference in JOB_TYPE_PREFERENCES else "实习"


def transition_job_type_preference(
    previous_platform_type,
    platform_job_type,
    selected_preference,
    remembered_preference,
):
    """同步平台筛选与优先性质，并记住“不限”时用户选择的排序偏好。"""
    selected = str(selected_preference or "").strip()
    remembered = str(remembered_preference or "").strip()
    if remembered not in JOB_TYPE_PREFERENCES:
        remembered = "实习"
    if selected not in JOB_TYPE_PREFERENCES:
        selected = remembered

    if previous_platform_type == "不限":
        remembered = selected

    platform_type = str(platform_job_type or "不限").strip()
    if platform_type in JOB_TYPE_PREFERENCES:
        selected = platform_type
    elif platform_type == "兼职":
        selected = remembered
    elif platform_type == "不限":
        selected = remembered

    return selected, remembered
