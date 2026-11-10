"""Run selected platforms sequentially with the existing shared daily ledger."""

from delivery_config import apply_search_settings, load_matching_config
from job_platforms import (
    PLATFORM_LABELS, ensure_platform_available, parse_platforms, platform_city_code,
)


def create_deliverer(platform, config, matching_context):
    ensure_platform_available(platform)
    if platform == "boss":
        from auto_deliver import AutoDeliverer, SpiderConfig, build_job_search_url

        apply_search_settings(config, SpiderConfig)
        SpiderConfig["keyword"] = matching_context["allocations"][0]["keyword"]
        SpiderConfig["start_url"] = build_job_search_url(SpiderConfig)
        return AutoDeliverer(config, matching_context=matching_context)

    from platform_deliverer import BrowserPlatformDeliverer

    platform_config = {**config, "platform_job_type": "不限"}
    return BrowserPlatformDeliverer(platform, platform_config, matching_context=matching_context)


def run_platforms(config):
    try:
        platforms = parse_platforms(config.get("platforms"))
        for platform in platforms:
            ensure_platform_available(platform)
            if platform != "boss":
                platform_city_code(platform, config)
        matching_context = load_matching_config(config)
    except (OSError, ValueError) as exc:
        print(f"[配置错误] {exc}")
        return 2

    exit_code = 0
    remaining = max(0, int(config.get("test_limit", 0) or 0))
    limited = remaining > 0
    for index, platform in enumerate(platforms, 1):
        if limited and remaining <= 0:
            break
        print(f"\n[平台] {index}/{len(platforms)} {PLATFORM_LABELS[platform]}")
        try:
            # Divide the remaining target so every selected platform gets a turn.
            platform_config = dict(config)
            if limited:
                platforms_left = len(platforms) - index + 1
                platform_config["test_limit"] = (remaining + platforms_left - 1) // platforms_left
            worker = create_deliverer(platform, platform_config, matching_context)
            result = worker.run() or 0
            if limited:
                remaining -= int(worker.stage_counts.get("ai_called", 0))
        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            print(f"[平台] {PLATFORM_LABELS[platform]}启动失败：{exc}")
            result = 1
        if result == 130:
            return 130
        if result:
            exit_code = max(exit_code, result)
    return exit_code
