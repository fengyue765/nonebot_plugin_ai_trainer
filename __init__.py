"""nonebot_plugin_ai_trainer — Yuri illustration with dual character fusion."""

import io
import asyncio
import aiohttp
import random
from datetime import datetime
from typing import Optional

from nonebot import on_command, on_message, require, get_bot
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    Message,
    MessageSegment,
    MessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from .config import Config
from .core.persona import persona_manager
from .core.prompts import prompt_enhancer
from .core.pipeline import generation_manager
from .core.filter import nsfw_filter
from .backend.comfy import ComfyClient


_comfy = ComfyClient()
_score_queue: dict[str, str] = {}
_learn_sessions: dict[str, tuple[str, int, list[bytes]]] = {}


def _is_superuser(event: Event) -> bool:
    return str(event.get_user_id()) == Config.SUPERUSER_ID


async def _generate_and_send(
    bot: Bot,
    user_id: str,
    nsfw_allowed: bool = False,
    persona1: Optional[dict] = None,
    persona2: Optional[dict] = None,
) -> None:
    """Generate a Yuri illustration with dual character fusion."""
    print(f"[DEBUG] ===== _generate_and_send 开始，用户={user_id} =====")
    print(f"[DEBUG] NSFW允许: {nsfw_allowed}")
    
    state = generation_manager.get_state(user_id)
    if not state or not state.active:
        print(f"[DEBUG] 用户 {user_id} 没有活跃的生成状态")
        return
    
    print(f"[DEBUG] 用户输入: {state.prompt}")
    p1_desc = persona1.get("description", "默认")[:50] if persona1 else "默认"
    p2_desc = persona2.get("description", "默认")[:50] if persona2 else ("同角色1" if persona1 else "默认")
    print(f"[DEBUG] 角色1: {p1_desc}")
    print(f"[DEBUG] 角色2: {p2_desc}")
    
    positive, negative = await prompt_enhancer.build_prompt(
        user_input=state.prompt,
        persona=persona1,
        persona2=persona2,
        refine=False,
        use_yuri_modifiers=True,
        use_style_modifiers=True,
        nsfw_allowed=nsfw_allowed,
        character_weight=1.5,  # 角色特征权重 1.4，强化角色特征
    )
    print(f"[DEBUG] 提示词构建完成")

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

    print(f"[DEBUG] 保存到历史记录")
    p1_name = persona_manager.get_persona_name(persona1) if persona1 else "default"
    p2_name = persona_manager.get_persona_name(persona2) if persona2 else p1_name
    persona_names = f"{p1_name}+{p2_name}"
    
    history_id = generation_manager.save_to_history(
        user_id=user_id,
        prompt=f"Yuri: {state.prompt} (角色: {persona_names})",
        final_positive=positive,
        final_negative=negative,
        image_bytes=image_bytes,
        persona_name=persona_names,
        score=None,
    )
    
    generation_manager.update_state_with_history(user_id, history_id)

    try:
        sent = await bot.send_private_msg(
            user_id=int(user_id),
            message=(
                MessageSegment.text(
                    f"[AI绘画] 百合插画生成完成\n"
                    "请回复评分 1-5（分数越高表示越满意）："
                )
                + MessageSegment.image(image_bytes)
            ),
        )
        msg_id = str(sent["message_id"])
        _score_queue[msg_id] = user_id
        print(f"[DEBUG] 图片发送成功")
        
    except Exception as exc:
        print(f"[DEBUG] 发送图片失败: {exc}")
    
    print(f"[DEBUG] ===== _generate_and_send 结束 =====\n")


# ---------------------------------------------------------------------------
# Score handler
# ---------------------------------------------------------------------------

score_matcher = on_message(priority=10, block=True)


@score_matcher.handle()
async def _handle_score(matcher: Matcher, event: MessageEvent) -> None:
    
    print(f"[DEBUG] 评分处理器开始")
    print(f"[DEBUG] 用户: {event.get_user_id()}, 内容: {event.get_plaintext()}")

    if not _is_superuser(event):
        await matcher.finish()
        return

    text = event.get_plaintext().strip()
    
    if text.startswith('/'):
        await matcher.finish()
        return
    
    if text not in ("1", "2", "3", "4", "5"):
        await matcher.finish()
        return

    score = int(text)
    user_id = str(event.get_user_id())
    
    state = generation_manager.get_state(user_id)
    if not state:
        await matcher.send("当前没有进行中的生成任务。请使用 /draw 开始新的生成。")
        await matcher.finish()
        return

    to_remove = [msg_id for msg_id, uid in _score_queue.items() if uid == user_id]
    for msg_id in to_remove:
        _score_queue.pop(msg_id, None)

    generation_manager.complete_generation(user_id, score)
    
    if score <= 2:
        await matcher.send(f"评分 {score}，已保存到历史记录。")
    else:
        await matcher.send(f"评分 {score}，图片已保存到历史记录！")
    
    await matcher.finish()


# ---------------------------------------------------------------------------
# /draw command - 支持双角色百合插图
# ---------------------------------------------------------------------------

draw_matcher = on_command("draw", aliases={"画画", "绘画"}, priority=5)


@draw_matcher.handle()
async def _handle_draw(matcher: Matcher, event: Event, args: Message = CommandArg()) -> None:
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    command_text = args.extract_plain_text().strip()
    if not command_text:
        await matcher.finish(
            "用法：/draw <角色1> + <角色2> <描述> [--nsfw[=强度]]\n"
            "示例：\n"
            "  /draw miyuki + mizuki 在樱花树下对视\n"
            "  /draw 白发少女 + 黑发少女 亲密拥抱 --nsfw"
            "强度范围: 0.1-1.0，默认0.4"
        )
    
    nsfw_allowed = "--nsfw" in command_text
    clean_text = command_text.replace("--nsfw", "").strip()
    
    persona1 = None
    persona2 = None
    user_prompt = clean_text
    
    # 解析双角色（使用 + 分隔）
    if "+" in clean_text:
        left, right = clean_text.split("+", 1)
        left = left.strip()
        right = right.strip()
        
        # 解析左侧角色
        left_words = left.split()
        left_name = left_words[0] if left_words else ""
        left_rest = " ".join(left_words[1:]) if len(left_words) > 1 else ""
        
        if left_name in persona_manager.list_personas():
            persona1 = persona_manager.get_persona(left_name)
        elif left_name:
            # 不是已学习角色，作为描述的一部分
            left_rest = left + " " + left_rest
        
        # 解析右侧角色
        right_words = right.split()
        right_name = right_words[0] if right_words else ""
        right_rest = " ".join(right_words[1:]) if len(right_words) > 1 else ""
        
        if right_name in persona_manager.list_personas():
            persona2 = persona_manager.get_persona(right_name)
        elif right_name:
            right_rest = right + " " + right_rest
        
        # 组合描述
        user_prompt = (left_rest + " " + right_rest).strip()
        
        # 如果第二个角色没有指定，使用第一个角色
        if not persona2:
            persona2 = persona1
    else:
        # 无 + 分隔符，尝试解析单个角色
        words = clean_text.split()
        if words and words[0] in persona_manager.list_personas():
            persona1 = persona_manager.get_persona(words[0])
            persona2 = persona1
            user_prompt = " ".join(words[1:]) if len(words) > 1 else ""
        else:
            user_prompt = clean_text
    
    if not user_prompt:
        user_prompt = "yuri, two girls, intimate"
    
    user_id = str(event.get_user_id())
    generation_manager.create_state(user_id, user_prompt)
    
    p1_name = persona_manager.get_persona_name(persona1) if persona1 else "默认"
    p2_name = persona_manager.get_persona_name(persona2) if persona2 else (p1_name if persona1 else "默认")
    
    await matcher.send(
        f"🎨 开始生成百合插图\n"
        f"角色1: {p1_name}\n"
        f"角色2: {p2_name}\n"
        f"描述: {user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}\n"
        f"正在生成中…"
    )

    try:
        bot = get_bot()
        await _generate_and_send(bot, user_id, nsfw_allowed, persona1, persona2)
    except Exception as exc:
        await matcher.finish(f"❌ 生成失败: {exc}")


# ---------------------------------------------------------------------------
# /list command
# ---------------------------------------------------------------------------

list_matcher = on_command("list", aliases={"角色列表"}, priority=5)


@list_matcher.handle()
async def _handle_list(matcher: Matcher, event: Event) -> None:
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    names = persona_manager.list_personas()

    if not names:
        await matcher.finish("暂无已学习的角色。使用 /learn <名称> 开始学习角色特征。")

    lines = ["🎨 已学习的角色："]
    for name in names:
        persona = persona_manager.get_persona(name)
        desc = persona.get("description", "")[:50] if persona else ""
        lines.append(f"• {name}：{desc}")

    await matcher.finish("\n".join(lines))


# ---------------------------------------------------------------------------
# /learn command
# ---------------------------------------------------------------------------

learn_matcher = on_command("learn", aliases={"学习角色"}, priority=5)


@learn_matcher.handle()
async def _handle_learn_start(
    matcher: Matcher, event: Event, args: Message = CommandArg()
) -> None:
    if not _is_superuser(event):
        await matcher.finish("仅超级用户可使用此命令")

    parts = args.extract_plain_text().strip().split()
    if len(parts) < 1:
        await matcher.finish("用法：/learn <角色名称> [图片数量]  例如：/learn miyuki 5")

    name = parts[0]
    try:
        count = int(parts[1]) if len(parts) > 1 else 3
        count = max(1, min(count, 20))
    except ValueError:
        await matcher.finish("图片数量必须是 1-20 之间的整数")

    user_id = str(event.get_user_id())
    _learn_sessions[user_id] = (name, count, [])

    await matcher.finish(
        f"📸 开始学习角色「{name}」的固定特征\n"
        f"请发送 {count} 张参考图片（建议不同角度）。"
    )


# ---------------------------------------------------------------------------
# Image collection for /learn
# ---------------------------------------------------------------------------

# Image collection for /learn
learn_image_matcher = on_message(priority=2, block=False)


@learn_image_matcher.handle()
async def _handle_learn_image(matcher: Matcher, event: MessageEvent) -> None:
    user_id = str(event.get_user_id())
    if user_id not in _learn_sessions:
        await matcher.finish()

    images_in_msg = [seg for seg in event.message if seg.type == "image"]
    if not images_in_msg:
        await matcher.finish()

    name, count, collected = _learn_sessions[user_id]

    async with aiohttp.ClientSession() as session:
        for seg in images_in_msg:
            url = seg.data.get("url") or seg.data.get("file")
            if not url:
                continue
            
            # 添加重试机制
            max_retries = 3
            retry_delay = 3
            timeout_seconds = 60
            success = False
            
            for attempt in range(max_retries):
                try:
                    print(f"[DEBUG] 下载图片尝试 {attempt + 1}/{max_retries}: {url}")
                    # 增加超时时间，添加更多headers模拟浏览器
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                    }
                    timeout = aiohttp.ClientTimeout(
                        total=timeout_seconds,      # 总超时
                        connect=15,                 # 连接超时
                        sock_read=timeout_seconds   # 读取超时
                    )
                    async with session.get(url, headers=headers, timeout=timeout) as resp:
                        if resp.status == 200:
                            # 使用 read() 而不是 json() 或 text()
                            img_data = await resp.read()
                            if img_data and len(img_data) > 100:  # 确保不是空文件
                                collected.append(img_data)
                                success = True
                                print(f"[DEBUG] 图片下载成功，大小: {len(img_data)} 字节")
                                break
                            else:
                                print(f"[DEBUG] 图片数据为空或太小: {len(img_data)} 字节")
                        else:
                            print(f"[DEBUG] HTTP错误: {resp.status}")
                except asyncio.TimeoutError:
                    print(f"[DEBUG] 下载超时 (尝试 {attempt + 1})")
                except aiohttp.ClientError as e:
                    print(f"[DEBUG] 客户端错误: {e}")
                except Exception as exc:
                    print(f"[DEBUG] 下载失败: {exc}")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
            
            if not success:
                await matcher.send(f"⚠️ 图片下载失败，请重试发送该图片")

    _learn_sessions[user_id] = (name, count, collected)
    remaining = count - len(collected)

    if remaining > 0:
        await matcher.send(
            f"已收到 {len(collected)}/{count} 张图片，还需 {remaining} 张。"
        )
        await matcher.finish()
        return

    # All images collected — tag them and build the persona
    await matcher.send(f"✅ 已收到全部 {count} 张图片，正在分析风格…")
    _learn_sessions.pop(user_id, None)

    all_tags: list[str] = []
    for idx, img_bytes in enumerate(collected):
        try:
            print(f"[DEBUG] 分析第 {idx + 1}/{count} 张图片")
            tags = await _comfy.get_image_tags(img_bytes)
            if tags:
                all_tags.append(tags)
                print(f"[DEBUG] 标签: {tags[:100]}...")
            else:
                print(f"[DEBUG] 未提取到标签")
        except Exception as exc:
            print(f"[DEBUG] get_image_tags 失败: {exc}")
            await matcher.send(f"⚠️ 第 {idx + 1} 张图片分析失败，继续处理...")

    if not all_tags:
        await matcher.send("⚠️ 未能提取到有效标签，使用默认风格")
        combined_tags = "anime style, 1girl"
    else:
        combined_tags = ", ".join(all_tags)

    try:
        persona = await persona_manager.create_persona_from_tags(name, combined_tags)
        await matcher.send(
            f"🎨 角色「{name}」学习完成！\n"
            f"固定特征：{persona['positive_prompt'][:150]}...\n"
            f"描述：{persona['description']}\n"
            f"使用 /draw {name} + [另一角色] <描述> 生成百合插图。"
        )
    except Exception as exc:
        print(f"[DEBUG] 角色创建失败: {exc}")
        await matcher.finish(f"❌ 角色创建失败: {exc}")