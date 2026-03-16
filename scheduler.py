# scheduler.py
import io
import random
import asyncio
from datetime import datetime

from nonebot import require, get_bot
from nonebot.adapters.onebot.v11 import MessageSegment

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .config import Config
from .engine import engine
from .manager import data_manager

# 全局待审核队列: { "msg_id": "pending_file_path" }
review_queue = {}

# 候选训练任务列表
_TASKS = [
    {"name": "step_1_skeleton", "prompt": "dynamic pose, fighting stance, anime style"},
    {"name": "step_1_skeleton", "prompt": "sitting pose, relaxed, anime style"},
    {"name": "step_2_sketch",   "prompt": "rough sketch, messy lines, 1girl, standing"},
    {"name": "step_2_sketch",   "prompt": "rough sketch, 1boy, running pose"},
    {"name": "step_3_lineart",  "prompt": "clean lineart, 1girl, detailed clothing"},
    {"name": "step_4_color",    "prompt": "flat color, anime, 1girl, blue hair"},
]


# 定时任务：每 120 分钟（2 小时）触发一次
@scheduler.scheduled_job(
    "interval",
    minutes=Config.SCHEDULER_INTERVAL_MINUTES,
    id="auto_paint",
)
async def auto_generate_task() -> None:
    """碎片时间标注任务：自动生成图片并私聊超级用户审核。

    只在每天 ``Config.SCHEDULER_START_HOUR`` 至
    ``Config.SCHEDULER_END_HOUR``（含）之间执行，避免深夜打扰。
    """
    now = datetime.now()
    if not (Config.SCHEDULER_START_HOUR <= now.hour <= Config.SCHEDULER_END_HOUR):
        return

    bot = get_bot()

    # 1. 随机挑选一个训练任务
    task = random.choice(_TASKS)
    print(f"[ai_trainer] 后台自动生成任务: {task['name']} | prompt: {task['prompt']}")

    # 2. 在线程池中调用引擎（避免阻塞事件循环）
    image, seed = await asyncio.to_thread(
        engine.generate_single, task["prompt"], task["name"]
    )

    # 3. 保存到 Pending 区
    meta = {"prompt": task["prompt"], "seed": seed, "source": "auto_scheduler"}
    file_path = data_manager.save_pending(image, task["name"], meta)

    # 4. 将图片编码为字节流后推送给超级用户
    img_byte = io.BytesIO()
    image.save(img_byte, format="PNG")

    try:
        msg = (
            MessageSegment.text(
                f"[碎片时间标注]\n任务: {task['name']}\nPrompt: {task['prompt']}\n"
            )
            + MessageSegment.image(img_byte.getvalue())
            + MessageSegment.text("\n回复 [ok] 归档，回复 [pass] 丢弃")
        )
        sent = await bot.send_private_msg(
            user_id=int(Config.SUPERUSER_ID), message=msg
        )

        # 记录消息 ID，供后续引用回复时查找
        msg_id = str(sent["message_id"])
        review_queue[msg_id] = file_path

    except Exception as e:
        print(f"[ai_trainer] 推送失败: {e}")
