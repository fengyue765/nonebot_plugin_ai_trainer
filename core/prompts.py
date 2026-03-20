"""Prompt enhancer for Yuri (girls' love) illustration generation with dual character fusion."""

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

# ========== 男性相关词汇（用于负面提示词）==========
_MALE_RELATED_TAGS = [
    # 基本男性称谓
    "male", "man", "men", "boy", "boys", "guy", "guys", "gentleman",
    "males", "male focus", "solo male",
    
    # 男性年龄/阶段
    "young man", "old man", "middle-aged man", "teenage boy", "adult male",
    "shota", "shouta",
    
    # 男性身体特征
    "muscular", "muscles", "abs", "six-pack", "pecs", "biceps",
    "broad shoulders", "chest hair", "facial hair", "beard", "mustache",
    "stubble", "goatee", "sideburns",
    
    # 男性发型
    "short hair male", "male haircut", "undercut male", "man bun",
    "bald male", "bald man", "shaved head",
    
    # 男性服装
    "suit male", "tuxedo", "male uniform", "male school uniform",
    "male gakuran", "male kimono", "male yukata",
    
    # 男性角色类型
    "bishounen", "bishonen", "ikemen", "ojisan", "ojii-san",
    "otoko", "dansei",
    
    # 男性职业/身份
    "salaryman", "butler male", "priest male", "teacher male", "student male",
    
    # 男性向/男性视角
    "male pov", "male perspective", "male gaze", "selfie male", "male selfie",
    
    # 父子/男性关系
    "father", "dad", "daddy", "papa", "son", "brother", "grandfather", "grandpa",
    "uncle", "nephew", "cousin male",
    
    # 男性群体
    "multiple males", "group of men", "all male", "male only",
    "boys club", "male harem", "reverse harem",
    
    # 男性性器官
    "penis", "cock", "dick", "phallus", "balls", "testicles", "scrotum",
    "male genitalia", "manhood", "erection", "erect", "hard-on", "boner",
    "sperm", "semen", "cum", "ejaculate", "precum", "pre-cum",
    "male pubic hair", "man pubic hair",
    
    # 男性 NSFW
    "cum on male", "male ejaculation", "male orgasm", "male cum",
    "sperm on face", "cum on body male", "male creampie",
    "male masturbation", "male fingering", "male handjob",
    "male receiving blowjob", "male giving blowjob",
    "male on top", "male dominant", "male submissive",
    "male x male", "mmf", "mm threesome", "male couple",
    "yaoi", "boys love", "bl", "shounen ai", "bara",
    "seme", "uke", "male kiss", "male kissing", "male hugging",
    "male nudity", "male naked", "male nude", "bulge", "male bulge",
    "tent", "visible bulge", "male underwear", "male boxers",
    "male briefs", "male stripping", "male strip",
    "male bound", "male bondage", "male tied", "male collar",
    "male slave", "male master", "father son", "dad son",
    "incest male", "family male", "relatives male",
    "sexy male", "hot male", "handsome male",
    "male seductive", "male provocative"
]

_MALE_NEGATIVE = ", ".join(_MALE_RELATED_TAGS)

# ========== 百合题材专属提示词 ==========

# 百合关系描述词库
_YURI_RELATIONSHIP_MODIFIERS = [
    "yuri", "girls love", "shoujo ai", "yuri couple",
    "two girls", "intimate", "close relationship", "affectionate",
    "gazing at each other", "holding hands", "embrace", "hug",
    "cuddling", "snuggling", "touching foreheads", "nuzzling"
]

# 百合氛围词库
_YURI_ATMOSPHERE_MODIFIERS = [
    "romantic atmosphere", "tender moment", "gentle mood", "warm feeling",
    "peaceful", "calm", "intimate atmosphere", "affectionate mood",
    "blooming love", "spring feeling", "sweet moment"
]

# 百合互动场景词库
_YURI_INTERACTION_MODIFIERS = [
    "face to face", "close together", "leaning on each other",
    "cheek to cheek", "foreheads touching", "nose to nose",
    "mutual affection", "loving gaze", "tender gaze"
]

# 所有百合修饰词合并
_YURI_MODIFIERS = {
    "relationship": _YURI_RELATIONSHIP_MODIFIERS,
    "atmosphere": _YURI_ATMOSPHERE_MODIFIERS,
    "interaction": _YURI_INTERACTION_MODIFIERS
}

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

def _add_yuri_modifiers(tags_str: str, intensity: float = 0.5) -> str:
    """
    向提示词添加百合题材的随机修饰词
    """
    if not tags_str:
        return tags_str
    
    selected_modifiers = []
    
    # 百合必选类别
    core_categories = ["relationship", "atmosphere"]
    for category in core_categories:
        modifiers = _YURI_MODIFIERS[category]
        if random.random() < intensity * 1.2:
            num_to_add = random.randint(1, min(2, len(modifiers)))
            selected = random.sample(modifiers, num_to_add)
            selected_modifiers.extend(selected)
            print(f"[DEBUG] 从百合类别 {category} 添加修饰词: {selected}")
    
    # 百合可选类别
    optional_categories = ["interaction"]
    for category in optional_categories:
        modifiers = _YURI_MODIFIERS[category]
        if random.random() < intensity * 0.8:
            num_to_add = random.randint(1, min(2, len(modifiers)))
            selected = random.sample(modifiers, num_to_add)
            selected_modifiers.extend(selected)
            print(f"[DEBUG] 从百合类别 {category} 添加修饰词: {selected}")
    
    if selected_modifiers:
        random.shuffle(selected_modifiers)
        modifiers_str = ", ".join(selected_modifiers)
        result = f"{tags_str}, {modifiers_str}"
        print(f"[DEBUG] 添加了 {len(selected_modifiers)} 个百合题材修饰词")
        return result
    
    return tags_str

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
    
    if len(tags) <= 5:  # 标签太少就不重新排列
        return tags_str
    
    # 固定前缀词（前几个重要的标签保持不变）
    fixed_count = min(5, len(tags))
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
    def __init__(
        self,
        ollama_url: str = Config.OLLAMA_URL,
        ollama_model: str = Config.OLLAMA_MODEL,
        yuri_intensity: float = 0.5,
        style_intensity: float = 0.2,  # 降低风格强度，突出角色
    ) -> None:
        self._ollama_url = ollama_url.rstrip("/")
        self._ollama_model = ollama_model
        self.yuri_intensity = yuri_intensity
        self.style_intensity = style_intensity

    def _split_character_tags(self, positive_prompt: str) -> List[str]:
        """将角色特征标签分割成独立标签，便于单独加权"""
        if not positive_prompt:
            return []
        return [tag.strip() for tag in positive_prompt.split(",") if tag.strip()]

    def _weight_character_tags(self, tags: List[str], weight: float = 1.3) -> List[str]:
        """为每个角色特征标签单独添加权重"""
        weighted = []
        for tag in tags:
            if ":" not in tag and "(" not in tag:
                weighted.append(f"({tag}:{weight})")
            else:
                weighted.append(tag)
        return weighted

    def fuse_character_prompts(
        self, 
        persona1: Optional[dict], 
        persona2: Optional[dict],
        weight: float = 1.3  # 角色特征权重
    ) -> Tuple[str, str]:
        """
        融合两个角色的固定特征提示词，并强化角色特征
        
        Args:
            persona1: 第一个角色的人格
            persona2: 第二个角色的人格
            weight: 角色特征的权重值 (1.2-1.5)
        
        Returns:
            (融合后的正面词, 融合后的负面词)
        """
        positive_parts = []
        negative_parts = []
        
        # 提取两个角色的正面特征，并为每个特征单独加权
        if persona1 and persona1.get("positive_prompt"):
            tags = self._split_character_tags(persona1["positive_prompt"])
            weighted_tags = self._weight_character_tags(tags, weight)
            positive_parts.append(", ".join(weighted_tags))
        
        if persona2 and persona2.get("positive_prompt"):
            # 如果角色2与角色1相同，使用相同的权重
            tags = self._split_character_tags(persona2["positive_prompt"])
            weight2 = weight if persona1 == persona2 else weight
            weighted_tags = self._weight_character_tags(tags, weight2)
            positive_parts.append(", ".join(weighted_tags))
        
        # 如果没有角色档案，使用默认描述（不加权重）
        if not positive_parts:
            positive_parts.append("1girl, beautiful, cute")
            positive_parts.append("another girl, beautiful, cute")
            # 为双人指示添加权重
            fused_positive = f"(2girls:{weight}), {', '.join(positive_parts)}"
        else:
            # 为双人指示添加权重，并确保角色特征在提示词开头
            fused_positive = f"(2girls:{weight}), {', '.join(positive_parts)}"
        
        # 融合负面词
        if persona1 and persona1.get("negative_prompt"):
            negative_parts.append(persona1["negative_prompt"])
        if persona2 and persona2.get("negative_prompt"):
            negative_parts.append(persona2["negative_prompt"])
        
        fused_negative = ", ".join(negative_parts) if negative_parts else ""
        
        return fused_positive, fused_negative

    async def build_prompt(
        self,
        user_input: str,
        persona: Optional[dict] = None,
        persona2: Optional[dict] = None,
        refine: bool = False,
        use_yuri_modifiers: bool = True,
        use_style_modifiers: bool = True,
        nsfw_allowed: bool = False,
        character_weight: float = 1.3,  # 角色特征权重
    ) -> tuple[str, str]:
        """
        构建百合插画提示词，强化角色特征
        
        Args:
            character_weight: 角色特征权重 (1.2-1.5 推荐)
        """
        # 第1步：融合角色特征（强化权重）
        fused_positive, fused_negative = self.fuse_character_prompts(
            persona, persona2, weight=character_weight
        )
        
        # 第2步：基础组合
        positive_parts = []
        
        # 角色特征放在最前面（最重要）
        if fused_positive:
            positive_parts.append(fused_positive)
        
        # 添加固定前缀（放在角色特征之后）
        if _FINAL_PROMPT_PREFIX:
            positive_parts.append(_FINAL_PROMPT_PREFIX)
        
        # 添加用户输入
        if user_input:
            positive_parts.append(user_input)
        
        positive = ", ".join(positive_parts)
        
        # 第3步：添加百合题材修饰词（降低强度，避免干扰角色）
        if use_yuri_modifiers:
            positive = _add_yuri_modifiers(positive, intensity=self.yuri_intensity * 0.8)
        
        # 第4步：添加二次元风格修饰词（降低强度）
        if use_style_modifiers:
            positive = _add_anime_modifiers(positive, intensity=self.style_intensity)
        
        # 第5步：随机扰动（只排列非角色特征部分）
        positive = _random_permute_tags(positive, permute_prob=0.15)
        
        # 第6步：为重要角色特征添加权重
        positive = _random_weight_tags(positive, weight_prob=0.2)
        
        # 第7步：去重处理
        positive = _deduplicate_tags(positive)
        
        # 第8步：NSFW过滤（移除男性相关词汇）
        positive, filtered_tags = nsfw_filter.filter_prompt(positive, nsfw_allowed)
        if filtered_tags:
            print(f"[DEBUG] NSFW过滤: 移除了 {len(filtered_tags)} 个标签")

        # ===== 负面提示词：固定负面词 + 男性相关词汇 + 角色负面词 =====
        negative_parts = [_FIXED_NEGATIVE, _MALE_NEGATIVE]
        if fused_negative:
            negative_parts.append(fused_negative)
        final_negative = ", ".join(negative_parts)

        print(f"[DEBUG] ===== PromptEnhancer.build_prompt =====")
        print(f"[DEBUG]   角色1特征: {persona['positive_prompt'][:50] if persona else '无'}")
        print(f"[DEBUG]   角色2特征: {persona2['positive_prompt'][:50] if persona2 else '同角色1'}")
        print(f"[DEBUG]   角色权重: {character_weight}")
        print(f"[DEBUG]   用户输入: {user_input[:50]}...")
        print(f"[DEBUG]   NSFW允许: {nsfw_allowed}")
        print(f"[DEBUG]   最终正面词: {positive[:150]}...")
        print(f"[DEBUG] ======================================")

        return positive, final_negative


prompt_enhancer = PromptEnhancer(yuri_intensity=0.5, style_intensity=0.2)