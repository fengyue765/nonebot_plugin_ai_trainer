# __init__.py
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, Event
from nonebot.rule import to_me
from .scheduler import review_queue
from .manager import data_manager

# 注册定时任务
from . import scheduler 

# 处理回复 "ok"
matcher_ok = on_command("ok", aliases={"不错", "保存"}, priority=5)

@matcher_ok.handle()
async def handle_ok(event: Event):
    # 获取用户回复的那条消息的 ID (Reply对象)
    reply = event.reply
    if not reply:
        await matcher_ok.finish("请引用(回复)机器人发的那张图说 ok")
        
    original_msg_id = str(reply.message_id)
    
    if original_msg_id in review_queue:
        file_path = review_queue.pop(original_msg_id)
        success, msg = data_manager.approve_data(file_path)
        await matcher_ok.finish(f"✅ {msg}")
    else:
        await matcher_ok.finish("这张图已经处理过了或不是待审核任务。")

# 处理回复 "pass"
matcher_pass = on_command("pass", aliases={"不行", "丢弃"}, priority=5)

@matcher_pass.handle()
async def handle_pass(event: Event):
    reply = event.reply
    if not reply:
        await matcher_pass.finish("请引用图片回复")
        
    original_msg_id = str(reply.message_id)
    
    if original_msg_id in review_queue:
        file_path = review_queue.pop(original_msg_id)
        success, msg = data_manager.reject_data(file_path)
        await matcher_pass.finish(f"🗑️ {msg}")
