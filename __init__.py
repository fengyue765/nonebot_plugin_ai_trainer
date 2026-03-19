"""nonebot_plugin_ai_trainer — AI painting training workflow plugin.

Commands
--------
/learn [name] [count]  Collect reference images to learn a new art style.
/use   [name]          Switch the active persona.
/list                  List available personas.
/draw  [prompt]        Start a new 4-stage painting pipeline.

Scheduled task
--------------
Every SCHEDULER_INTERVAL_HOURS (default 2) between SCHEDULER_START_HOUR and
SCHEDULER_END_HOUR the bot advances any active pipeline one step and sends the
result to the superuser for scoring (1-5).
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

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .config import Config
from .core.persona import persona_manager
from .core.prompts import prompt_enhancer
from .core.pipeline import pipeline_manager
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


async def _run_pipeline_step(
    bot: Bot,
    user_id: str,
) -> None:
    """Run the current pipeline step for a user and send the result."""
    state = pipeline_manager.get_state(user_id)
    if not state or state.is_complete:
        return

    step = state.current_step
    if step is None:
        return

    persona = persona_manager.active_persona
    positive, negative = await prompt_enhancer.build_prompt(
        step=step,
        user_input=state.prompt,
        persona=persona,
        refine=True,
    )

    label = Config.PIPELINE_STEP_LABELS.get(step, step)
    step_index = state.current_step_index + 1
    total = len(Config.PIPELINE_STEPS)

    try:
        if step == "sketch":
            image_bytes = await _comfy.step1_sketch(positive, negative)
        else:
            prev_step = Config.PIPELINE_STEPS[state.current_step_index - 1]
            prev_path = state.step_images.get(prev_step)
            if prev_path:
                from pathlib import Path
                prev_bytes = Path(prev_path).read_bytes()
            else:
                prev_bytes = await _comfy.step1_sketch(positive, negative)
            image_bytes = await _comfy.stepx_img2img(prev_bytes, positive, negative)
    except Exception as exc:
        await bot.send_private_msg(
            user_id=int(user_id),
            message=f"❌ 步骤 {label} 生成失败: {exc}",
        )
        return

    pipeline_manager.save_step_image(user_id, step, image_bytes)

    try:
        sent = await bot.send_private_msg(
            user_id=int(user_id),
            message=(
                MessageSegment.text(
                    f"[AI绘画] 步骤 {step_index}/{total}: {label}\n"
                    f"提示词: {positive}\n"
                    "请回复评分 1-5（1-2=重做，3-5=继续下一步）："
                )
                + MessageSegment.image(image_bytes)
            ),
        )
        msg_id = str(sent["message_id"])
        _score_queue[msg_id] = user_id
    except Exception as exc:
        print(f"[ai_trainer] 发送图片失败: {exc}")


# ---------------------------------------------------------------------------
# Scheduled task
# ---------------------------------------------------------------------------

@scheduler.scheduled_job(
    "interval",
    hours=Config.SCHEDULER_INTERVAL_HOURS,
    id="ai_trainer_pipeline",
)
async def _scheduled_pipeline_advance() -> None:
    """Advance all active pipelines every SCHEDULER_INTERVAL_HOURS hours."""
    now = datetime.now()
    if not (Config.SCHEDULER_START_HOUR <= now.hour <= Config.SCHEDULER_END_HOUR):
        return

    try:
        bot = get_bot()
    except Exception:
        return

    user_id = Config.SUPERUSER_ID
    state = pipeline_manager.get_state(user_id)
    if state and not state.is_complete:
        await _run_pipeline_step(bot, user_id)


# ---------------------------------------------------------------------------
# Score handler (intercepts plain 1-5 replies that quote a known message)
# ---------------------------------------------------------------------------

score_matcher = on_message(priority=1, block=False)


@score_matcher.handle()
async def _handle_score(matcher: Matcher, event: MessageEvent) -> None:
    
    # --- DEBUG START ---
    print(f"[DEBUG] _handle_score triggered by user: {event.get_user_id()}")
    print(f"[DEBUG] Message content: {event.get_plaintext()}")
    # --- DEBUG END ---

    if not _is_superuser(event):
        await matcher.finish()

    reply = getattr(event, "reply", None)
    if not reply:
        await matcher.finish()

    ref_id = str(reply.message_id)
    if ref_id not in _score_queue:
        await matcher.finish()

    # --- DEBUG START ---
    print(f"[DEBUG] Reply Ref ID: {ref_id}")
    print(f"[DEBUG] Current Score Queue keys: {list(_score_queue.keys())}")
    # --- DEBUG END ---

    text = event.get_plaintext().strip()
    if text not in ("1", "2", "3", "4", "5"):
        await matcher.finish()

    score = int(text)
    user_id = _score_queue.pop(ref_id)

    # --- DEBUG START ---
    print(f"[DEBUG] Valid score: {score} from user {user_id}")
    # --- DEBUG END ---

    try:
        bot = get_bot()
    except Exception:
        await matcher.finish()

    state = pipeline_manager.get_state(user_id)
    # --- DEBUG START ---
    print(f"[DEBUG] Pipeline state for user {user_id}: {state}")
    if state:
        print(f"[DEBUG] Current step: {state.current_step}")
    # --- DEBUG END ---
    if not state:
        await matcher.finish("当前没有进行中的流水线。")

    step_label = Config.PIPELINE_STEP_LABELS.get(state.current_step or "", "")

    if score <= 2:
        await matcher.send(f"😕 评分 {score}，重新生成 {step_label}…")
        await _run_pipeline_step(bot, user_id)
    else:
        await matcher.send(f"✅ 评分 {score}，{step_label} 通过，进入下一步…")
        next_step = pipeline_manager.advance_step(user_id)
        state = pipeline_manager.get_state(user_id)
        if state and not state.is_complete:
            await _run_pipeline_step(bot, user_id)
        else:
            await matcher.send("🎉 绘画流水线已完成！")


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
    pipeline_manager.create_state(user_id, prompt)

    await matcher.send(f"🎨 开始新的绘画流水线：{prompt}\n第一步：草图生成中…")

    try:
        bot = get_bot()
        await _run_pipeline_step(bot, user_id)
    except Exception as exc:
        await matcher.finish(f"❌ 启动流水线失败: {exc}")


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

