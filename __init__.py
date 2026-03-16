# __init__.py
"""nonebot_plugin_ai_trainer 插件入口。

命令列表
--------
/paint | /画画 [主题描述]
    手动触发一次完整的 4 阶段绘画流水线。
    若提供主题描述则使用该描述；否则从 Config.SUBJECT_POOL 中随机选取。

1 / 2 / 3 / 4 / 5  （引用回复机器人发送的阶段图片）
    对当前阶段进行评分：
    · 1-2 分 → 重新生成本阶段（保存评分数据后重做）
    · 3-5 分 → 归档并推进到下一阶段

ok | 保存  （引用回复）
    等同于 5 分，归档并推进。

pass | 丢弃  （引用回复）
    等同于 1 分，重新生成本阶段。
"""

import random
from pathlib import Path

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    Message,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from PIL import Image

from .config import Config
from .manager import data_manager

# 注册定时任务（副作用：scheduler.py 中的 @scheduler.scheduled_job 会在此时绑定）
from . import scheduler as _scheduler_module
from .scheduler import _pipeline_sessions, start_pipeline, _run_stage


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _is_superuser(event: Event) -> bool:
    """判断消息发送者是否为配置文件中指定的超级用户。"""
    return str(event.get_user_id()) == Config.SUPERUSER_ID


async def _handle_rating(
    bot: Bot,
    event: PrivateMessageEvent,
    rating: int,
) -> None:
    """处理用户对阶段图片的评分。

    Args:
        bot:    NoneBot Bot 实例。
        event:  触发事件（需含引用回复）。
        rating: 用户给出的评分，1-5 的整数。
    """
    reply = event.reply
    if not reply:
        await bot.send_private_msg(
            user_id=int(Config.SUPERUSER_ID),
            message="⚠️ 请**引用（回复）**机器人发送的阶段图片后再发送评分。",
        )
        return

    msg_id = str(reply.message_id)
    session = _pipeline_sessions.get(msg_id)

    if session is None:
        await bot.send_private_msg(
            user_id=int(Config.SUPERUSER_ID),
            message="⚠️ 该图片已处理过或不属于待审核任务。",
        )
        return

    # 从注册表中取出（无论结果如何都先移除，防止重复处理）
    _pipeline_sessions.pop(msg_id)

    stage = Config.PIPELINE_STAGES[session.stage_index]

    if rating <= 2:
        # 低分：丢弃并重新生成本阶段
        data_manager.reject_data(session.pending_path)
        await bot.send_private_msg(
            user_id=int(Config.SUPERUSER_ID),
            message=f"🔄 {rating} 分，重新生成「{stage['label']}」…",
        )
        # stage_index 不变，stage_images 不增加（重新生成同一阶段）
        await _run_stage(session)
    else:
        # 高分：归档并推进到下一阶段
        _ok, msg = data_manager.approve_data(session.pending_path)
        await bot.send_private_msg(
            user_id=int(Config.SUPERUSER_ID),
            message=f"✅ {rating} 分，{msg}",
        )
        # 将当前阶段的输出图片加入 stage_images，供下一阶段的 ControlNet 使用
        train_img_path = (
            data_manager.train_dir
            / stage["name"]
            / Path(session.pending_path).name
        )
        if train_img_path.exists():
            session.stage_images.append(Image.open(train_img_path))

        session.stage_index += 1
        await _run_stage(session)


# ---------------------------------------------------------------------------
# 命令：ok / 保存
# ---------------------------------------------------------------------------
matcher_ok = on_command("ok", aliases={"保存", "不错"}, priority=5)


@matcher_ok.handle()
async def handle_ok(bot: Bot, matcher: Matcher, event: PrivateMessageEvent):
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令。")
    await _handle_rating(bot, event, rating=5)
    await matcher.finish()


# ---------------------------------------------------------------------------
# 命令：pass / 丢弃
# ---------------------------------------------------------------------------
matcher_pass = on_command("pass", aliases={"丢弃", "不行"}, priority=5)


@matcher_pass.handle()
async def handle_pass(bot: Bot, matcher: Matcher, event: PrivateMessageEvent):
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令。")
    await _handle_rating(bot, event, rating=1)
    await matcher.finish()


# ---------------------------------------------------------------------------
# 数字评分（1-5）：用户直接引用回复图片并输入数字
# ---------------------------------------------------------------------------
def _is_rating_message(event: Event) -> bool:
    """规则函数：消息为 '1'~'5' 的纯文本且含引用回复时返回 True。"""
    if not isinstance(event, PrivateMessageEvent):
        return False
    if not _is_superuser(event):
        return False
    text = event.get_plaintext().strip()
    return text in {"1", "2", "3", "4", "5"} and event.reply is not None


matcher_rating = on_message(rule=_is_rating_message, priority=4, block=True)


@matcher_rating.handle()
async def handle_rating_msg(bot: Bot, matcher: Matcher, event: PrivateMessageEvent):
    rating = int(event.get_plaintext().strip())
    await _handle_rating(bot, event, rating=rating)
    await matcher.finish()


# ---------------------------------------------------------------------------
# 命令：/paint | /画画 — 手动触发流水线
# ---------------------------------------------------------------------------
matcher_paint = on_command("paint", aliases={"画画", "绘画"}, priority=5)


@matcher_paint.handle()
async def handle_paint(
    bot: Bot, matcher: Matcher, event: PrivateMessageEvent, args: Message = CommandArg()
):
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令。")

    subject = args.extract_plain_text().strip()
    if not subject:
        subject = random.choice(Config.SUBJECT_POOL)

    await matcher.send(
        f"🎨 开始绘制：{subject}\n"
        f"共 {len(Config.PIPELINE_STAGES)} 个阶段，请逐阶段评分（1-5 分）。"
    )
    await start_pipeline(subject=subject, source="manual")
