# scheduler.py
"""定时任务模块：每 3 小时（仅在 8:00-23:00 之间）自动触发一次绘画流水线。

流程：
1. 从 Config.SUBJECT_POOL 随机选取一条主题描述。
2. 生成阶段 1（构图）图片并发送给超级用户。
3. 等待用户评分（1-5 分）；评分存于 `__init__.py` 管理的 `_pipeline_sessions` 中。
4. 后续阶段由 `__init__.py` 中的评分回调驱动（≤2 分重做，>2 分推进）。
"""

import asyncio
import random
from datetime import datetime

from nonebot import get_bot, require

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler  # noqa: E402

from .config import Config
from .engine import engine
from .manager import data_manager
from .utils import image_to_bytes


# ---------------------------------------------------------------------------
# 全局流水线会话注册表（由 __init__.py 引用）
# ---------------------------------------------------------------------------
# Key: bot 已发送消息的 message_id（字符串）
# Value: PipelineSession 实例
_pipeline_sessions: dict[str, "PipelineSession"] = {}


class PipelineSession:
    """记录一次完整 4 阶段绘画任务的运行状态。

    Attributes:
        subject:        本次创作的主题描述。
        stage_index:    当前正在等待评分的阶段索引（0-3）。
        stage_images:   已完成阶段的输出图片列表（长度 = stage_index）。
        pending_path:   当前阶段图片在 pending 目录的磁盘路径。
        source:         触发来源，``"scheduler"`` 或 ``"manual"``。
    """

    def __init__(self, subject: str, source: str = "scheduler") -> None:
        self.subject = subject
        self.stage_index: int = 0
        self.stage_images: list = []        # 已通过阶段的 PIL.Image 列表
        self.pending_path: str = ""
        self.source = source


async def start_pipeline(subject: str, source: str = "scheduler") -> None:
    """启动一次完整的 4 阶段流水线并发送阶段 1 图片给超级用户。

    Args:
        subject: 主题描述词，会注入到各阶段的 prompt_template。
        source:  触发来源标识（用于元数据记录）。
    """
    session = PipelineSession(subject=subject, source=source)
    await _run_stage(session)


async def _run_stage(session: PipelineSession) -> None:
    """生成当前阶段图片，保存至 pending，并发送私信给超级用户。

    Args:
        session: 当前流水线会话实例。
    """
    stages = Config.PIPELINE_STAGES
    idx = session.stage_index

    if idx >= len(stages):
        # 所有阶段已完成
        try:
            bot = get_bot()
            await bot.send_private_msg(
                user_id=int(Config.SUPERUSER_ID),
                message=f"🎉 流水线完成！主题：{session.subject}",
            )
        except Exception as e:
            print(f"[ai_trainer] 发送完成通知失败: {e}")
        return

    stage = stages[idx]
    prev_image = session.stage_images[-1] if session.stage_images else None

    prompt = stage["prompt_template"].format(subject=session.subject)
    stage_config = {
        "prompt": prompt,
        "controlnet": stage["controlnet"],
        "scale": stage["scale"],
    }

    print(
        f"[ai_trainer] 开始阶段 {idx + 1}/{len(stages)}: {stage['name']} "
        f"| 主题: {session.subject}"
    )

    try:
        image, seed = await asyncio.to_thread(engine.generate, stage_config, prev_image)
    except Exception as e:
        print(f"[ai_trainer] 阶段 {stage['name']} 生成失败: {e}")
        return

    # 保存到 pending 目录
    meta = {
        "prompt": prompt,
        "seed": seed,
        "subject": session.subject,
        "stage": stage["name"],
        "stage_label": stage["label"],
        "source": session.source,
    }
    session.pending_path = data_manager.save_pending(image, stage["name"], meta)

    # 私聊超级用户
    try:
        from nonebot.adapters.onebot.v11 import MessageSegment

        msg = (
            MessageSegment.text(
                f"[AI训练师] {stage['label']} ({idx + 1}/{len(stages)})\n"
                f"主题：{session.subject}\n"
                f"Prompt：{prompt}\n\n"
                "请**引用本条消息**回复评分（1-5 分）：\n"
                "  1-2 分 → 重新生成本阶段\n"
                "  3-5 分 → 归档并进入下一阶段\n"
                "也可直接回复 ok（相当于5分）或 pass（相当于1分）"
            )
            + MessageSegment.image(image_to_bytes(image))
        )
        bot = get_bot()
        sent = await bot.send_private_msg(
            user_id=int(Config.SUPERUSER_ID), message=msg
        )
        msg_id = str(sent["message_id"])
        _pipeline_sessions[msg_id] = session
        print(f"[ai_trainer] 阶段 {stage['name']} 已发送，消息ID: {msg_id}")
    except Exception as e:
        print(f"[ai_trainer] 发送阶段 {stage['name']} 消息失败: {e}")


# ---------------------------------------------------------------------------
# 定时任务：每 3 小时触发一次，仅在 [SCHEDULE_START_HOUR, SCHEDULE_END_HOUR]
# ---------------------------------------------------------------------------
@scheduler.scheduled_job(
    "cron",
    hour=f"{Config.SCHEDULE_START_HOUR}-{Config.SCHEDULE_END_HOUR}/3",
    minute=0,
    id="ai_trainer_auto",
)
async def auto_pipeline_task() -> None:
    """每 3 小时自动触发一次绘画流水线（仅在配置的时间窗口内）。"""
    now = datetime.now()
    if not (Config.SCHEDULE_START_HOUR <= now.hour <= Config.SCHEDULE_END_HOUR):
        return

    subject = random.choice(Config.SUBJECT_POOL)
    print(f"[ai_trainer] 定时任务触发 | 时间: {now.strftime('%H:%M')} | 主题: {subject}")
    await start_pipeline(subject=subject, source="scheduler")
