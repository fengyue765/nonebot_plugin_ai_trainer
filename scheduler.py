# scheduler.py
from nonebot import require, get_bot
from nonebot.adapters.onebot.v11 import MessageSegment
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler
from .engine import engine
from .manager import data_manager
import random
import asyncio

# 全局待审核队列: { "uuid_msg_id": "pending_file_path" }
review_queue = {}

# 定时任务：每 60 分钟自动生成一张图
@scheduler.scheduled_job("interval", minutes=60, id="auto_paint")
async def auto_generate_task():
    bot = get_bot()
    # 请填入你的 QQ 号，让机器人只私聊你
    SUPERUSER_ID = "123456789" 
    
    # 1. 随机挑选一个训练任务
    # 为了演示，我们随机选一个步骤和Prompt
    steps = [
        {"name": "step_1_skeleton", "prompt": "dynamic pose, fighting stance"},
        {"name": "step_2_sketch", "prompt": "rough sketch, messy lines, 1girl, sitting"},
    ]
    task = random.choice(steps)
    
    # 2. 调用引擎生成 (异步)
    # 注意：engine 需要适配 generate_image 单独方法
    print(f"后台自动生成任务: {task['name']}")
    image, seed = await asyncio.to_thread(engine.generate_single, task["prompt"])
    
    # 3. 保存到 Pending 区
    meta = {"prompt": task["prompt"], "seed": seed, "source": "auto_scheduler"}
    file_path = data_manager.save_pending(image, task["name"], meta)
    
    # 4. 推送给用户
    import io
    img_byte = io.BytesIO()
    image.save(img_byte, format='PNG')
    
    try:
        msg = (
            MessageSegment.text(f"[碎片时间标注]\n任务: {task['name']}\nPrompt: {task['prompt']}\n") + 
            MessageSegment.image(img_byte.getvalue()) +
            MessageSegment.text("\n回复 [ok] 归档，回复 [pass] 丢弃")
        )
        sent = await bot.send_private_msg(user_id=int(SUPERUSER_ID), message=msg)
        
        # 记录消息ID，以便后续引用回复
        msg_id = str(sent['message_id'])
        review_queue[msg_id] = file_path
        
    except Exception as e:
        print(f"推送失败: {e}")
