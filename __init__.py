# __init__.py
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Event
from nonebot.matcher import Matcher

from .config import Config
from .scheduler import review_queue
from .manager import data_manager

# 注册定时任务
from . import scheduler


def _is_superuser(event: Event) -> bool:
    """检查事件发送者是否为配置中指定的超级用户。"""
    return str(event.get_user_id()) == Config.SUPERUSER_ID


# 处理回复 "ok"
matcher_ok = on_command("ok", aliases={"不错", "保存"}, priority=5)


@matcher_ok.handle()
async def handle_ok(matcher: Matcher, event: Event):
    # 仅超级用户可操作
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    # 获取用户回复的那条消息的 ID (Reply 对象)
    reply = event.reply
    if not reply:
        await matcher.finish("请引用(回复)机器人发的那张图说 ok")

    original_msg_id = str(reply.message_id)

    if original_msg_id in review_queue:
        file_path = review_queue.pop(original_msg_id)
        success, msg = data_manager.approve_data(file_path)
        await matcher.finish(f"✅ {msg}")
    else:
        await matcher.finish("这张图已经处理过了或不是待审核任务。")


# 处理回复 "pass"
matcher_pass = on_command("pass", aliases={"不行", "丢弃"}, priority=5)


@matcher_pass.handle()
async def handle_pass(matcher: Matcher, event: Event):
    # 仅超级用户可操作
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    reply = event.reply
    if not reply:
        await matcher.finish("请引用图片回复")

    original_msg_id = str(reply.message_id)

    if original_msg_id in review_queue:
        file_path = review_queue.pop(original_msg_id)
        success, msg = data_manager.reject_data(file_path)
        await matcher.finish(f"🗑️ {msg}")
    else:
        await matcher.finish("这张图已经处理过了或不是待审核任务。")
