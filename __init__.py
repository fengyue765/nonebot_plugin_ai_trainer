"""nonebot_plugin_ai_trainer — AI painting plugin (single-step generation).

Commands
--------
/learn [name] [count]  Collect reference images to learn a new art style.
/use   [name]          Switch the active persona.
/list                  List available personas.
/draw  [prompt]        Generate a single image using the current style.
"""

import io
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional

from nonebot import on_command, on_message, require, get_bot
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    Message,
    MessageSegment,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

# 注释掉定时任务依赖
# require("nonebot_plugin_apscheduler")
# from nonebot_plugin_apscheduler import scheduler

from .config import Config
from .core.persona import persona_manager
from .core.prompts import prompt_enhancer
from .core.pipeline import generation_manager  # 改为使用新的 generation_manager
from .backend.comfy import ComfyClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_comfy = ComfyClient()

# Pending score queue: maps sent message_id → user_id
_score_queue: dict[str, str] = {}

# Pending learn sessions: maps user_id → (persona_name, expected_count, collected_images)
_learn_sessions: dict[str, tuple[str, int, list[bytes]]] = {}


def _is_superuser(event: Event) -> bool:
    return str(event.get_user_id()) == Config.SUPERUSER_ID


async def _generate_and_send(
    bot: Bot,
    user_id: str,
) -> None:
    """Generate a single image using current persona and send the result."""
    print(f"[DEBUG] ===== _generate_and_send 开始，用户={user_id} =====")
    
    state = generation_manager.get_state(user_id)
    if not state or not state.active:
        print(f"[DEBUG] 用户 {user_id} 没有活跃的生成状态")
        return
    
    print(f"[DEBUG] 获取到生成状态: {state}")

    # 获取当前激活的人格
    persona = persona_manager.active_persona
    persona_name = persona_manager.active_name
    print(f"[DEBUG] 当前人格: {persona_name}")
    
    print(f"[DEBUG] 开始构建提示词，用户输入: {state.prompt}")
    positive, negative = await prompt_enhancer.build_prompt(
        user_input=state.prompt,
        persona=persona,
        refine=True,
    )
    print(f"[DEBUG] 提示词构建完成")
    print(f"[DEBUG] 正面词: {positive[:100]}...")
    print(f"[DEBUG] 负面词: {negative[:100]}...")

    try:
        print(f"[DEBUG] 开始调用 ComfyUI step1_sketch")
        image_bytes = await _comfy.step1_sketch(positive, negative)
        print(f"[DEBUG] ComfyUI 生成成功，图片大小: {len(image_bytes)} 字节")
    except Exception as exc:
        print(f"[DEBUG] ComfyUI 生成失败: {exc}")
        await bot.send_private_msg(
            user_id=int(user_id),
            message=f"❌ 图片生成失败: {exc}",
        )
        return

    # 先保存到未评分历史
    print(f"[DEBUG] 保存到历史记录")
    history_id = generation_manager.save_to_history(
        user_id=user_id,
        prompt=state.prompt,
        final_positive=positive,
        final_negative=negative,
        image_bytes=image_bytes,
        persona_name=persona_name,
        score=None,  # 未评分
    )
    print(f"[DEBUG] 历史记录ID: {history_id}")
    
    # 更新状态关联历史记录
    generation_manager.update_state_with_history(user_id, history_id)
    print(f"[DEBUG] 已更新状态关联")

    try:
        print(f"[DEBUG] 发送图片给用户")
        sent = await bot.send_private_msg(
            user_id=int(user_id),
            message=(
                MessageSegment.text(
                    f"[AI绘画] 图片生成完成\n"
                    f"提示词: {positive}\n"
                    "请回复评分 1-5（分数越高表示越满意）："
                )
                + MessageSegment.image(image_bytes)
            ),
        )
        
        # 仍然记录消息ID，但不是必须的（为了兼容性）
        msg_id = str(sent["message_id"])
        _score_queue[msg_id] = user_id
        print(f"[DEBUG] 图片发送成功，消息ID: {msg_id}（仅用于兼容性记录）")
        
    except Exception as exc:
        print(f"[DEBUG] 发送图片失败: {exc}")
    
    print(f"[DEBUG] ===== _generate_and_send 结束 =====\n")


# 注释掉定时任务
# @scheduler.scheduled_job(
#     "interval",
#     hours=Config.SCHEDULER_INTERVAL_HOURS,
#     id="ai_trainer_pipeline",
# )
# async def _scheduled_pipeline_advance() -> None:
#     """Advance all active pipelines every SCHEDULER_INTERVAL_HOURS hours."""
#     now = datetime.now()
#     if not (Config.SCHEDULER_START_HOUR <= now.hour <= Config.SCHEDULER_END_HOUR):
#         return
# 
#     try:
#         bot = get_bot()
#     except Exception:
#         return
# 
#     user_id = Config.SUPERUSER_ID
#     state = pipeline_manager.get_state(user_id)
#     if state and not state.is_complete:
#         await _run_pipeline_step(bot, user_id)


# ---------------------------------------------------------------------------
# Score handler (intercepts plain 1-5 replies that quote a known message)
# ---------------------------------------------------------------------------

score_matcher = on_message(priority=10, block=True)


@score_matcher.handle()
async def _handle_score(matcher: Matcher, event: MessageEvent) -> None:
    
    print(f"[DEBUG] ===== 评分处理器开始 =====")
    print(f"[DEBUG] _handle_score triggered by user: {event.get_user_id()}")
    print(f"[DEBUG] Message content: {event.get_plaintext()}")
    print(f"[DEBUG] Full message: {event.message}")

    # 检查是否是超级用户
    if not _is_superuser(event):
        print(f"[DEBUG] 不是超级用户，结束")
        await matcher.finish()
        return

    print(f"[DEBUG] _is_superuser pass")

    # 获取消息内容
    text = event.get_plaintext().strip()
    
    # 检查消息内容是否是1-5的数字
    if text not in ("1", "2", "3", "4", "5"):
        print(f"[DEBUG] 消息内容 '{text}' 不是有效的评分")
        await matcher.finish()
        return

    print(f"[DEBUG] 有效评分: {text}")

    # 获取用户ID
    user_id = str(event.get_user_id())
    
    # 检查用户是否有进行中的生成任务
    state = generation_manager.get_state(user_id)
    if not state:
        print(f"[DEBUG] 用户 {user_id} 没有进行中的生成任务")
        await matcher.send("当前没有进行中的生成任务。请使用 /draw 开始新的生成。")
        await matcher.finish()
        return
    
    print(f"[DEBUG] 获取到生成状态: {state}")

    score = int(text)
    
    # 不需要从评分队列中获取，因为我们已经取消了这个限制
    # 但为了兼容性，仍然检查一下评分队列（可能还有旧数据）
    if _score_queue:
        # 清理所有属于该用户的旧评分队列条目
        to_remove = [msg_id for msg_id, uid in _score_queue.items() if uid == user_id]
        for msg_id in to_remove:
            _score_queue.pop(msg_id, None)
        print(f"[DEBUG] 清理了 {len(to_remove)} 条旧评分队列记录")

    try:
        bot = get_bot()
        print(f"[DEBUG] 成功获取bot")
    except Exception as e:
        print(f"[DEBUG] 获取bot失败: {e}")
        await matcher.finish()
        return

    if score <= 2:
        print(f"[DEBUG] 低分处理: {score}")
        await matcher.send(f"😕 评分 {score}，已保存到历史记录，重新生成图片…")
        
        # 先完成当前生成（移动到评分目录）
        generation_manager.complete_generation(user_id, score)
        print(f"[DEBUG] 已完成当前生成并移动到评分 {score} 目录")
        
        # 创建新状态并重新生成
        generation_manager.create_state(user_id, state.prompt)
        print(f"[DEBUG] 已创建新生成状态，提示词: {state.prompt}")
        
        await _generate_and_send(bot, user_id)
        print(f"[DEBUG] 已调用 _generate_and_send")
        
        await matcher.finish()
    else:
        print(f"[DEBUG] 高分处理: {score}")
        await matcher.send(f"✅ 评分 {score}，图片已保存到历史记录！")
        generation_manager.complete_generation(user_id, score)
        print(f"[DEBUG] 已完成生成并移动到评分 {score} 目录")
        
        await matcher.send(f"🎉 图片已保存到评分 {score} 的历史记录中！")
        await matcher.finish()
    
    print(f"[DEBUG] ===== 评分处理器结束 =====\n")


# ---------------------------------------------------------------------------
# /draw command
# ---------------------------------------------------------------------------

draw_matcher = on_command("draw", aliases={"画画", "绘画"}, priority=5)


@draw_matcher.handle()
async def _handle_draw(matcher: Matcher, event: Event, args: Message = CommandArg()) -> None:
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    prompt = args.extract_plain_text().strip()
    if not prompt:
        await matcher.finish("用法：/draw <描述>  例如：/draw 1girl, blue hair, anime style")

    user_id = str(event.get_user_id())
    generation_manager.create_state(user_id, prompt)

    await matcher.send(f"🎨 开始生成图片：{prompt}\n正在生成中…")

    try:
        bot = get_bot()
        await _generate_and_send(bot, user_id)
    except Exception as exc:
        await matcher.finish(f"❌ 生成失败: {exc}")


# ---------------------------------------------------------------------------
# /use command
# ---------------------------------------------------------------------------

use_matcher = on_command("use", aliases={"切换风格"}, priority=5)


@use_matcher.handle()
async def _handle_use(matcher: Matcher, event: Event, args: Message = CommandArg()) -> None:
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    name = args.extract_plain_text().strip()
    if not name:
        await matcher.finish("用法：/use <风格名称>")

    if persona_manager.switch_persona(name):
        await matcher.finish(f"✅ 已切换到风格：{name}")
    else:
        names = persona_manager.list_personas()
        hint = "、".join(names) if names else "（暂无风格，请先用 /learn 学习）"
        await matcher.finish(f"❌ 风格 '{name}' 不存在。可用风格：{hint}")


# ---------------------------------------------------------------------------
# /list command
# ---------------------------------------------------------------------------

list_matcher = on_command("list", aliases={"列表", "风格列表"}, priority=5)


@list_matcher.handle()
async def _handle_list(matcher: Matcher, event: Event) -> None:
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    names = persona_manager.list_personas()
    active = persona_manager.active_name

    if not names:
        await matcher.finish("暂无已学习的风格。使用 /learn <名称> 开始学习。")

    lines = []
    for name in names:
        persona = persona_manager.get_persona(name)
        marker = " ← 当前" if name == active else ""
        desc = persona.get("description", "") if persona else ""
        lines.append(f"• {name}{marker}：{desc}")

    await matcher.finish("🎨 已学习的风格：\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# /learn command
# ---------------------------------------------------------------------------

learn_matcher = on_command("learn", aliases={"学习风格"}, priority=5)


@learn_matcher.handle()
async def _handle_learn_start(
    matcher: Matcher, event: Event, args: Message = CommandArg()
) -> None:
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    parts = args.extract_plain_text().strip().split()
    if len(parts) < 1:
        await matcher.finish("用法：/learn <名称> [图片数量]  例如：/learn miyazaki 5")

    name = parts[0]
    try:
        count = int(parts[1]) if len(parts) > 1 else 3
        count = max(1, min(count, 10))
    except ValueError:
        await matcher.finish("图片数量必须是 1-10 之间的整数")

    user_id = str(event.get_user_id())
    _learn_sessions[user_id] = (name, count, [])

    await matcher.finish(
        f"📸 开始学习风格「{name}」，请接下来发送 {count} 张参考图片（每次发一张）。"
    )


# Image collection for /learn
learn_image_matcher = on_message(priority=2, block=False)


@learn_image_matcher.handle()
async def _handle_learn_image(matcher: Matcher, event: MessageEvent) -> None:
    user_id = str(event.get_user_id())
    if user_id not in _learn_sessions:
        await matcher.finish()

    images_in_msg = [
        seg for seg in event.message if seg.type == "image"
    ]
    if not images_in_msg:
        await matcher.finish()

    name, count, collected = _learn_sessions[user_id]

    async with aiohttp.ClientSession() as session:
        for seg in images_in_msg:
            url = seg.data.get("url") or seg.data.get("file")
            if not url:
                continue
            try:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    collected.append(await resp.read())
            except Exception as exc:
                await matcher.send(f"⚠️ 图片下载失败: {exc}")

    _learn_sessions[user_id] = (name, count, collected)
    remaining = count - len(collected)

    if remaining > 0:
        await matcher.send(
            f"已收到 {len(collected)}/{count} 张图片，还需 {remaining} 张。"
        )
        await matcher.finish()

    # All images collected — tag them and build the persona
    await matcher.send(f"✅ 已收到全部 {count} 张图片，正在分析风格…")
    _learn_sessions.pop(user_id, None)

    all_tags: list[str] = []
    for img_bytes in collected:
        try:
            tags = await _comfy.get_image_tags(img_bytes)
            if tags:
                all_tags.append(tags)
        except Exception as exc:
            print(f"[ai_trainer] get_image_tags failed: {exc}")

    combined_tags = ", ".join(all_tags) if all_tags else "anime style"

    try:
        persona = await persona_manager.create_persona_from_tags(name, combined_tags)
        await matcher.send(
            f"🎨 风格「{name}」学习完成！\n"
            f"正向提示词：{persona['positive_prompt']}\n"
            f"描述：{persona['description']}\n"
            f"使用 /use {name} 切换到该风格。"
        )
    except Exception as exc:
        await matcher.finish(f"❌ 风格创建失败: {exc}")