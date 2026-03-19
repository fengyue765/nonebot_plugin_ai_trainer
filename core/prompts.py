"""Prompt enhancer (simplified for single-step generation with deduplication and random perturbations)."""

import aiohttp
import random
import re
from typing import Optional, List, Tuple

from ..config import Config
from ..backend.comfy import comfy_client
from .filter import nsfw_filter  # 导入过滤器

# 固定前缀词 - 用于提升生成质量
_FINAL_PROMPT_PREFIX = (
    "score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up, "
    "source_anime, anime style, manga style, Japanese animation, "
    "masterpiece quality, best quality, high quality, highly detailed, "
    "professional lighting, cinematic lighting, dynamic shading, "
    "detailed rendering, vibrant anime colors, clean lines, "
    "beautiful character illustration, trending on Pixiv, "
    "anime key visual, digital anime art"
)

# 固定负面词 - 用于避免低质量输出
_FIXED_NEGATIVE = (
    "score_4, score_3, score_2, score_1, score_0, text, watermark, "
    "ugly, worst quality, low quality, normal quality, bad anatomy, "
    "bad hands, missing fingers, extra fingers, extra limbs, "
    "fused fingers, deformed hands, malformed limbs, blurry, grainy, "
    "noisy, pixelated, low resolution, signature, username, artist name, "
    "text, letters, words, logo, title, caption, date, "
    "western comic style, American comic, realistic, 3d, photorealistic"
)

# ========== 二次元风格随机扰动词库 ==========

# 画风/画师风格词库
_ARTIST_STYLE_MODIFIERS = [
    "shaft style", "kyoto animation style", "ufotable style", "cloverworks style",
    "trigger style", "bones style", "madhouse style", "wit studio style",
    "akira toriyama style", "hayao miyazaki style", "makoto shinkai style",
    "yoshitoshi abe style", "yuki kajiura style", "range murata style",
    "pixiv trending style", "danbooru style", "safebooru style"
]

# 画面精细度修饰词
_DETAIL_MODIFIERS = [
    "highly detailed", "intricate details", "detailed background", "detailed eyes",
    "detailed hair", "detailed clothing", "detailed accessories", "intricate linework",
    "sharp lines", "clean lines", "delicate lines", "thick lines", "thin lines",
    "detailed illustration", "fine details", "ornate details", "detailed textures"
]

# 上色风格词库
_COLORING_STYLE_MODIFIERS = [
    "cel shade", "soft shade", "smooth shading", "flat colors", "gradient shading",
    "anime coloring", "manga coloring", "pastel colors", "vibrant colors",
    "watercolor style", "airbrush style", "digital coloring", "traditional coloring",
    "bright colors", "soft colors", "warm colors", "cool colors", "monochrome"
]

# 光影效果词库
_LIGHTING_STYLE_MODIFIERS = [
    "soft lighting", "dramatic lighting", "backlighting", "rim lighting",
    "sunlight", "moonlight", "candlelight", "studio lighting",
    "god rays", "volumetric lighting", "ambient light", "glowing effect",
    "light rays", "shadow", "reflected light", "transparent light"
]

# 特效/氛围词库
_EFFECT_MODIFIERS = [
    "sparkles", "glitter", "glow", "aura", "particles", "sakura petals",
    "bubbles", "sparkling effect", "magic circle", "magic effect",
    "shining eyes", "tears", "blush", "sweatdrop", "speed lines",
    "effect lines", "concentration lines", "background effect"
]

# 角色特征词库
_CHARACTER_FEATURE_MODIFIERS = [
    "beautiful eyes", "sparkling eyes", "shiny hair", "flowing hair", "twin tails",
    "long hair", "short hair", "ponytail", "bob cut", "blonde hair", "brown hair",
    "black hair", "white hair", "blue hair", "red hair", "purple hair", "green hair",
    "school uniform", "kimono", "yukata", "maid outfit", "casual wear", "sweater",
    "hoodie", "jacket", "dress", "skirt", "jeans", "shorts", "leggings", "thighhighs"
]

# 表情词库
_EXPRESSION_MODIFIERS = [
    "smile", "happy smile", "gentle smile", "sad smile", "crying smile", "tears",
    "angry", "pout", "blush", "embarrassed", "surprised", "shocked", "scared",
    "determined", "serious", "cool", "calm", "relaxed", "sleepy", "tired",
    "excited", "joyful", "happy", "sad", "lonely", "thoughtful", "thinking"
]

# 构图角度词库
_ANGLE_MODIFIERS = [
    "from above", "from below", "from side", "from behind", "close-up",
    "face focus", "eye focus", "upper body", "full body", "knee up",
    "thigh up", "waist up", "chest up", "head shot", "dynamic angle",
    "low angle", "high angle", "bird's eye view", "worm's eye view"
]

# 背景类型词库
_BACKGROUND_MODIFIERS = [
    "simple background", "white background", "gradient background", "blurry background",
    "detailed background", "cityscape background", "nature background", "forest background",
    "ocean background", "sky background", "clouds background", "stars background",
    "abstract background", "pattern background", "sakura background", "night background",
    "day background", "sunset background", "dawn background", "room background"
]

# 所有二次元风格修饰词合并
_ANIME_MODIFIERS = {
    "artist_style": _ARTIST_STYLE_MODIFIERS,
    "detail": _DETAIL_MODIFIERS,
    "coloring": _COLORING_STYLE_MODIFIERS,
    "lighting": _LIGHTING_STYLE_MODIFIERS,
    "effect": _EFFECT_MODIFIERS,
    "character": _CHARACTER_FEATURE_MODIFIERS,
    "expression": _EXPRESSION_MODIFIERS,
    "angle": _ANGLE_MODIFIERS,
    "background": _BACKGROUND_MODIFIERS
}


def _deduplicate_tags(tags_str: str) -> str:
    """
    使用 set 去重提示词中的重复标签
    
    Args:
        tags_str: 逗号分隔的标签字符串
    
    Returns:
        去重后的逗号分隔字符串
    """
    if not tags_str:
        return ""
    
    # 分割标签
    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]
    
    # 使用 dict.fromkeys() 来保持顺序（Python 3.7+ 字典保持插入顺序）
    seen = {}
    unique_tags = []
    
    for tag in tags:
        # 转换为小写进行比较，但保留原始格式用于输出
        tag_lower = tag.lower()
        if tag_lower not in seen:
            seen[tag_lower] = True
            unique_tags.append(tag)
    
    # 调试信息
    if len(tags) != len(unique_tags):
        print(f"[DEBUG] 去重前: {len(tags)} 个标签，去重后: {len(unique_tags)} 个标签")
    
    return ", ".join(unique_tags)


def _add_anime_modifiers(tags_str: str, intensity: float = 0.4) -> str:
    """
    向提示词添加二次元风格的随机修饰词
    
    Args:
        tags_str: 原始提示词
        intensity: 扰动强度 (0.0-1.0)，控制添加修饰词的数量
    
    Returns:
        添加随机修饰词后的提示词
    """
    if not tags_str:
        return tags_str
    
    # 决定要添加哪些类别的修饰词
    selected_modifiers = []
    
    # 二次元风格必选类别（强度较高）
    core_categories = ["artist_style", "detail", "coloring", "lighting"]
    for category in core_categories:
        modifiers = _ANIME_MODIFIERS[category]
        if random.random() < intensity * 1.2:  # 核心类别有更高概率
            num_to_add = random.randint(1, min(2, len(modifiers)))
            selected = random.sample(modifiers, num_to_add)
            selected_modifiers.extend(selected)
            print(f"[DEBUG] 从核心类别 {category} 添加修饰词: {selected}")
    
    # 可选类别（强度较低）
    optional_categories = ["effect", "expression", "angle", "background"]
    for category in optional_categories:
        modifiers = _ANIME_MODIFIERS[category]
        if random.random() < intensity * 0.8:  # 可选类别概率较低
            num_to_add = random.randint(1, min(2, len(modifiers)))
            selected = random.sample(modifiers, num_to_add)
            selected_modifiers.extend(selected)
            print(f"[DEBUG] 从可选类别 {category} 添加修饰词: {selected}")
    
    # 如果选择了修饰词，添加到原提示词末尾
    if selected_modifiers:
        # 随机打乱顺序
        random.shuffle(selected_modifiers)
        modifiers_str = ", ".join(selected_modifiers)
        result = f"{tags_str}, {modifiers_str}"
        print(f"[DEBUG] 添加了 {len(selected_modifiers)} 个二次元风格随机修饰词")
        return result
    
    return tags_str


def _random_permute_tags(tags_str: str, permute_prob: float = 0.2) -> str:
    """
    随机重新排列部分标签的顺序
    
    Args:
        tags_str: 原始提示词
        permute_prob: 每个标签被重新排列的概率
    
    Returns:
        重新排列后的提示词
    """
    if not tags_str:
        return tags_str
    
    # 分割标签
    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]
    
    if len(tags) <= 3:  # 标签太少就不重新排列
        return tags_str
    
    # 固定前缀词（前几个重要的标签保持不变）
    fixed_count = min(3, len(tags))
    fixed_tags = tags[:fixed_count]
    rest_tags = tags[fixed_count:]
    
    if not rest_tags:
        return tags_str
    
    # 对剩余标签进行随机排列
    random.shuffle(rest_tags)
    
    result_tags = fixed_tags + rest_tags
    print(f"[DEBUG] 重新排列了 {len(rest_tags)} 个标签的顺序")
    
    return ", ".join(result_tags)


def _random_weight_tags(tags_str: str, weight_prob: float = 0.15) -> str:
    """
    为部分重要标签添加权重 (tag:1.2 格式)
    
    Args:
        tags_str: 原始提示词
        weight_prob: 每个标签被加权的概率
    
    Returns:
        添加权重后的提示词
    """
    if not tags_str:
        return tags_str
    
    # 分割标签
    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]
    
    weighted_tags = []
    weighted_count = 0
    
    # 重要关键词列表（这些词有更高概率被加权）
    important_keywords = [
        "anime style", "masterpiece", "best quality", "highly detailed",
        "beautiful", "cute", "beautiful eyes", "sparkling eyes"
    ]
    
    for tag in tags:
        should_weight = False
        
        # 检查是否是重要关键词
        if any(keyword in tag.lower() for keyword in important_keywords):
            should_weight = random.random() < weight_prob * 1.5  # 重要词有更高概率
        else:
            should_weight = random.random() < weight_prob
        
        if should_weight and ":" not in tag and "(" not in tag:  # 避免重复加权
            # 随机选择权重 (1.1-1.3)
            weight = round(random.uniform(1.1, 1.3), 1)
            weighted_tags.append(f"({tag}:{weight})")
            weighted_count += 1
        else:
            weighted_tags.append(tag)
    
    if weighted_count > 0:
        print(f"[DEBUG] 为 {weighted_count} 个标签添加了权重")
    
    return ", ".join(weighted_tags)


class PromptEnhancer:
    """Builds final prompts for single-step generation using fixed templates + persona + user input."""

    def __init__(
        self,
        ollama_url: str = Config.OLLAMA_URL,
        ollama_model: str = Config.OLLAMA_MODEL,
        perturbation_intensity: float = 0.4,  # 默认扰动强度40%
    ) -> None:
        self._ollama_url = ollama_url.rstrip("/")
        self._ollama_model = ollama_model
        self.perturbation_intensity = perturbation_intensity

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def build_prompt(
        self,
        user_input: str,
        persona: Optional[dict] = None,
        refine: bool = False,
        use_perturbation: bool = True,
        nsfw_allowed: bool = False,  # 是否允许 NSFW
    ) -> tuple[str, str]:
        """Build (positive, negative) prompts for final generation.

        提示词构建流程：
        1. 基础组合：固定前缀 + 角色档案正面词 + 用户输入
        2. 随机扰动：添加随机修饰词、重新排列、添加权重
        3. 去重处理：移除重复标签
        4. NSFW过滤：最后执行过滤（男性词始终过滤，其他NSFW词根据nsfw_allowed决定）

        Args:
            user_input: The raw user-provided description.
            persona:    Optional persona dict with positive_prompt.
            refine:     Kept for compatibility but not used.
            use_perturbation: Whether to add random perturbations.
            nsfw_allowed: Whether NSFW content is allowed.

        Returns:
            (positive_prompt, negative_prompt) tuple.
        """
        # 获取角色档案中的正面提示词
        persona_positive = persona["positive_prompt"] if persona else ""
        
        # ===== 第1步：基础组合 =====
        positive_parts = []
        
        # 添加固定前缀
        if _FINAL_PROMPT_PREFIX:
            positive_parts.append(_FINAL_PROMPT_PREFIX)
        
        # 添加角色档案正面词
        if persona_positive:
            positive_parts.append(persona_positive)
        
        # 添加用户输入
        if user_input:
            positive_parts.append(user_input)
        
        # 用逗号连接所有部分
        positive = ", ".join(positive_parts)
        
        # ===== 第2步：随机扰动 =====
        if use_perturbation:
            print(f"[DEBUG] ===== 开始应用二次元风格随机扰动 =====")
            print(f"[DEBUG] 扰动强度: {self.perturbation_intensity}")
            
            # 1. 添加二次元风格修饰词
            positive = _add_anime_modifiers(positive, intensity=self.perturbation_intensity)
            
            # 2. 随机重新排列部分标签
            positive = _random_permute_tags(positive, permute_prob=self.perturbation_intensity * 0.5)
            
            # 3. 随机为部分重要标签添加权重
            positive = _random_weight_tags(positive, weight_prob=self.perturbation_intensity * 0.4)
            
            print(f"[DEBUG] ===== 随机扰动应用完成 =====")

        # ===== 第3步：去重处理 =====
        positive = _deduplicate_tags(positive)
        
        # ===== 第4步：NSFW过滤（最后执行） =====
        positive, filtered_tags = nsfw_filter.filter_prompt(positive, nsfw_allowed)
        
        # 如果有标签被过滤，记录日志
        if filtered_tags:
            print(f"[DEBUG] NSFW过滤: 移除了 {len(filtered_tags)} 个标签")

        # ===== 负面提示词：固定负面词 =====
        final_negative = _FIXED_NEGATIVE

        # 添加调试信息
        # print(f"[DEBUG] ===== PromptEnhancer.build_prompt =====")
        # print(f"[DEBUG]   固定前缀: {_FINAL_PROMPT_PREFIX[:50]}...")
        # print(f"[DEBUG]   角色正面: {persona_positive[:50] if persona_positive else '无'}")
        # print(f"[DEBUG]   用户输入: {user_input[:50]}...")
        # print(f"[DEBUG]   扰动强度: {self.perturbation_intensity if use_perturbation else '禁用'}")
        # print(f"[DEBUG]   NSFW允许: {nsfw_allowed}")
        # print(f"[DEBUG]   最终正面词: {positive[:100]}...")
        # print(f"[DEBUG] ======================================")

        return positive, final_negative

    # ------------------------------------------------------------------
    # 扰动强度控制
    # ------------------------------------------------------------------

    def set_perturbation_intensity(self, intensity: float) -> None:
        """设置随机扰动强度 (0.0-1.0)"""
        self.perturbation_intensity = max(0.0, min(1.0, intensity))
        print(f"[DEBUG] 扰动强度已设置为: {self.perturbation_intensity}")

    # ------------------------------------------------------------------
    # Ollama refinement (disabled)
    # ------------------------------------------------------------------

    async def _refine_with_ollama(self, prompt: str) -> str:
        """Ollama refinement is disabled. Returns original prompt."""
        return prompt


# Module-level singleton
prompt_enhancer = PromptEnhancer(perturbation_intensity=0.4)