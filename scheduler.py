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


# 定时任务：每 SCHEDULER_INTERVAL_MINUTES 分钟触发一次
@scheduler.scheduled_job(
    "interval",
    minutes=Config.SCHEDULER_INTERVAL_MINUTES,
    id="auto_paint",
)
async def auto_generate_task() -> None:
    """碎片时间标注任务：按完整绘画流水线自动生成图片并私聊超级用户审核。

    每次触发时：
    1. 从 Config.SUBJECT_POOL 随机选取一条主题描述（代表最终成品图的要求）。
    2. 依次执行 Config.PIPELINE_STEPS 中定义的全部绘画步骤：
       骨架/定位 → 外貌/背景轮廓草图 → 细化草图 × 2 → 线稿 →
       上大底色 → 细化色块 → 调色 → 光影完稿。
       主题描述自动注入各步骤的提示词模板，无需手动填写每步 prompt。
    3. 每个步骤的输出图像作为下一步骤的 ControlNet 条件输入，实现逐步精修。
    4. 每步结果单独推送给超级用户审核（ok/pass）。

    只在每天 Config.SCHEDULER_START_HOUR 至 Config.SCHEDULER_END_HOUR
    （含）之间执行，避免深夜打扰。
    """
    now = datetime.now()
    if not (Config.SCHEDULER_START_HOUR <= now.hour <= Config.SCHEDULER_END_HOUR):
        return

    bot = get_bot()

    # 1. 随机选取主题描述（最终成品图的完整要求）
    subject = random.choice(Config.SUBJECT_POOL)
    total = len(Config.PIPELINE_STEPS)
    print(f"[ai_trainer] 开始完整流水线 | 主题: {subject} | 共 {total} 步")

    prev_image = None
    for idx, step in enumerate(Config.PIPELINE_STEPS, start=1):
        # 2. 将主题描述注入当前步骤的提示词模板
        prompt = step["prompt_template"].format(subject=subject)
        step_config = {
            "prompt": prompt,
            "controlnet_conditioning_scale": step["controlnet_conditioning_scale"],
        }
        print(
            f"[ai_trainer] 步骤 {idx}/{total}: {step['name']} ({step['label']}) "
            f"| scale={step['controlnet_conditioning_scale']} | prompt: {prompt}"
        )

        # 3. 在线程池中调用引擎（避免阻塞事件循环）
        try:
            image, seed = await asyncio.to_thread(
                engine.generate, step_config, prev_image
            )
        except Exception as e:
            print(f"[ai_trainer] 步骤 {step['name']} 生成失败: {e}")
            break

        # 4. 保存到 Pending 区
        meta = {
            "prompt": prompt,
            "seed": seed,
            "source": "auto_scheduler",
            "subject": subject,
            "step": step["name"],
            "step_label": step["label"],
        }
        file_path = data_manager.save_pending(image, step["name"], meta)

        # 5. 将图片编码为字节流后推送给超级用户审核
        img_byte = io.BytesIO()
        image.save(img_byte, format="PNG")

        try:
            msg = (
                MessageSegment.text(
                    f"[碎片时间标注] {step['label']} ({idx}/{total})\n"
                    f"主题: {subject}\n"
                    f"步骤: {step['name']}\n"
                    f"Prompt: {prompt}\n"
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
            print(f"[ai_trainer] 步骤 {step['name']} 推送失败: {e}")

        # 6. 以当前步骤输出作为下一步骤的 ControlNet 条件图
        prev_image = image

    print(f"[ai_trainer] 流水线完成 | 主题: {subject}")
