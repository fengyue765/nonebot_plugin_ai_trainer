"""NSFW tag filter module.

Filters out NSFW tags from prompts unless explicitly allowed with --nsfw parameter.
"""

import re
from typing import List, Set, Tuple, Optional

# ========== NSFW 标签黑名单 ==========

# 性行为相关
_SEXUAL_ACT_TAGS = {
    "sex", "fucking", "fuck", "intercourse", "copulating", "mating",
    "penetration", "vaginal", "anal", "oral", "blowjob", "bj", "fellatio",
    "cunnilingus", "rimjob", "handjob", "footjob", "paizuri", "titfuck",
    "threesome", "foursome", "gangbang", "orgy", "group sex",
    "fingering", "fisted", "fisting", "dildo", "vibrator", "sex toy",
    "missionary", "cowgirl", "reverse cowgirl", "doggy", "doggystyle",
    "sixty nine", "69", "spooning", "standing sex", "against wall",
    "on bed", "on floor", "on couch", "bathroom sex", "shower sex",
    "masturbation",  # 自慰
    "squirting",     # 潮吹
    "kiss", "kissing",  # 接吻
    "fingering",     # 指交
    "69", "sixty nine",  # 69式
}

# 性器官相关 - 男性
_MALE_GENITALIA_TAGS = {
    "penis", "cock", "dick", "phallus", "balls", "testicles", "scrotum",
    "male genitalia", "manhood", "erection", "erect", "hard-on", "boner",
    "sperm", "semen", "cum", "ejaculate", "precum", "pre-cum",
    "male pubic hair", "man pubic hair",
}

# 性器官相关 - 女性
_FEMALE_GENITALIA_TAGS = {
    "vagina", "pussy", "cunt", "clitoris", "clit", "labia", "vulva",
    "nipples", "areola", "breasts", "tits", "boobs", "bust", "chest",
    "female pubic hair", "pussy juice", "female_pubic_hair",
    "large_breasts", "breasts_out", "nipples",
}

# 体液相关
_BODY_FLUID_TAGS = {
    "cum", "semen", "sperm", "ejaculate", "ejaculation", "creampie",
    "facial", "cumshot", "bukakke", "piss", "urine", "watersports",
    "sweat", "drool", "saliva", "spit", "lube", "lubricant",
    "squirting",  # 潮吹
    "pussy_juice",  # 阴部液体
}

# 暴露/衣着相关
_EXPOSURE_TAGS = {
    "naked", "nude", "nudity", "bare", "strip", "stripping", "undressed",
    "topless", "bottomless", "no clothes", "no underwear", "no bra",
    "no panties", "panties around one leg", "bra lift", "skirt lift",
    "clothes lift", "shirt lift", "shorts pull", "pants pull",
    "see-through", "transparent", "sheer", "wet clothes", "clingy",
    "braless", "nipple slip", "underwear", "lingerie", "bikini", "swimsuit",
    "open_clothes",      # 敞开衣服
    "open_shirt",        # 敞开衬衫
    "breasts_out",       # 乳房露出
    "panties_around_one_leg",  # 内裤挂在一条腿上
    "thigh_strap",       # 大腿带
    "censored",          # 审查（暗示有敏感内容）
    "monochrome",        # 单色（常用于成人内容）
    "underwear",         # 内衣
    "panties",           # 内裤
    "no_bra",            # 无胸罩
    "bar_censor",        # 条形审查
}

# 性暗示姿势
_SUGGESTIVE_POSES = {
    "spread legs", "open legs", "legs apart", "wide stance",
    "on back", "on stomach", "on all fours", "bent over",
    "presenting", "arched back", "arched", "bending over",
    "upskirt", "downblouse", "wardrobe malfunction",
    "provocative", "seductive", "seductive pose", "seductive look",
    "spread_legs",       # 张开双腿
    "arms_behind_back",  # 手臂背后
    "sitting_on_lap",    # 坐在腿上
    "sitting_on_person", # 坐在人身上
    "on bed",            # 在床上
    "on couch",          # 在沙发上
}

# BDSM/束缚相关
_BDSM_TAGS = {
    "bound", "bdsm", "bondage", "bound_wrists", "rope", "ribbon",
    "domination", "submission", "master", "slave", "petplay",
    "chained", "shackles", "handcuffs", "harness", "collar",
    "ball_gag", "gag", "blindfold", "leash", "whip", "paddle",
    "restraints", "tied", "tied_up", "spreader_bar",
    "arms_behind_back",  # 手臂背后
    "bound_wrists",      # 手腕被绑
    "rope",              # 绳子
    "ribbon",            # 丝带
    "thigh_strap",       # 大腿带
    "collar",            # 项圈
}

# 成人内容标记
_ADULT_CONTENT_TAGS = {
    "nsfw", "r18", "adult", "mature", "explicit", "erotic", "porn",
    "hentai", "ero", "ecchi", "smut", "lewd", "pervert", "perverted",
    "kink", "kinky", "bdsm", "bondage", "domination", "submission",
    "master", "slave", "petplay", "roleplay",
    "yuri",              # 百合（女同性恋）
    "censored",          # 审查
    "monochrome",        # 单色
    "bar_censor",        # 条形审查
}

# 男性角色相关词汇（始终过滤）
_MALE_CHARACTER_TAGS = {
    # 基本男性称谓
    "male", "man", "men", "boy", "boys", "guy", "guys", "gentleman",
    "males", "male focus", "solo male",
    
    # 男性年龄/阶段
    "young man", "old man", "middle-aged man", "teenage boy", "adult male",
    "shota", "shouta",  # 正太（幼年男性）
    
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
    "bishounen", "bishonen",  # 美少年
    "ikemen",  # 帅哥
    "ojisan",  # 大叔
    "ojii-san",  # 爷爷
    "otoko",  # 男（日语）
    "dansei",  # 男性（日语）
    
    # 男性职业/身份
    "salaryman",  # 上班族男性
    "butler male",  # 男管家
    "priest male",  # 男祭司
    "teacher male",  # 男教师
    "student male",  # 男学生
    
    # 男性向/男性视角
    "male pov", "male perspective", "male gaze",
    "selfie male", "male selfie",
    
    # 父子/男性关系
    "father", "dad", "daddy", "papa",
    "son", "brother", "grandfather", "grandpa",
    "uncle", "nephew", "cousin male",
    
    # 男性群体
    "multiple males", "group of men", "all male", "male only",
    "boys club", "male harem", "reverse harem",
}

# 男性相关的 NSFW 词汇（始终过滤）
_MALE_NSFW_TAGS = {
    # 男性性器官（已包含在 _MALE_GENITALIA_TAGS）
    "penis", "cock", "dick", "balls", "testicles", "scrotum",
    
    # 男性射精相关
    "cum on male", "male ejaculation", "male orgasm", "male cum",
    "sperm on face", "cum on body male", "male creampie",
    
    # 男性性行为（主动/被动）
    "male masturbation", "male fingering", "male handjob",
    "male receiving blowjob", "male giving blowjob",
    "male on top", "male dominant", "male submissive",
    
    # 男男相关
    "male x male", "mmf", "mm threesome", "male couple",
    "yaoi", "boys love", "bl", "shounen ai", "bara",
    "seme", "uke",  # 攻受
    "male kiss", "male kissing", "male hugging",
    
    # 男性暴露
    "male nudity", "male naked", "male nude",
    "bulge", "male bulge", "tent", "visible bulge",
    "male underwear", "male boxers", "male briefs",
    "male stripping", "male strip",
    
    # 男性 BDSM
    "male bound", "male bondage", "male tied",
    "male collar", "male slave", "male master",
    
    # 父子/乱伦相关
    "father son", "dad son", "incest male",
    "family male", "relatives male",
    
    # 男性角色性化
    "sexy male", "hot male", "handsome male",
    "male seductive", "male provocative",
}

# 合并所有 NSFW 标签
_NSFW_TAGS = (
    _SEXUAL_ACT_TAGS |
    _MALE_GENITALIA_TAGS |
    _FEMALE_GENITALIA_TAGS |
    _BODY_FLUID_TAGS |
    _EXPOSURE_TAGS |
    _SUGGESTIVE_POSES |
    _BDSM_TAGS |
    _ADULT_CONTENT_TAGS |
    _MALE_NSFW_TAGS
)

# 转换为小写集合便于匹配
_NSFW_TAGS_LOWER = {tag.lower() for tag in _NSFW_TAGS}

# 需要精确匹配的标签（避免误伤）
_EXACT_MATCH_ONLY = {
    "hole", "bare", "on back", "on stomach", "bent over", "arched",
    "ribbon",  # 丝带（也可能是普通装饰）
    "collar",  # 项圈（也可能是普通服装）
    "rope",    # 绳子（也可能是普通道具）
    "sweat",   # 汗水（也可能是正常出汗）
    "heart",   # 心形（可能是正常装饰）
    "kiss",    # 接吻（也可能是友好亲吻）
    "bulge",   # 凸起（也可能是衣服褶皱）
    "tent",    # 帐篷（也可能是露营用品）
}

# 安全组合（避免误伤）
_SAFE_COMBINATIONS = [
    # (nsfw词, 安全短语)
    ("breast", "breast pocket"),
    ("breast", "breastplate"),
    ("nipple", "nipple ring"),      # 饰品
    ("nipple", "nipple piercing"),  # 饰品
    ("strap", "shoulder strap"),    # 服装部件
    ("strap", "bag strap"),         # 包带
    ("strap", "watch strap"),       # 表带
    ("collar", "shirt collar"),     # 衣领
    ("collar", "fur collar"),       # 毛领
    ("collar", "lace collar"),      # 蕾丝领
    ("ribbon", "hair ribbon"),      # 发带
    ("ribbon", "ribbon bow"),       # 蝴蝶结
    ("ribbon", "ribbon tie"),       # 丝带领带
    ("rope", "rope bridge"),        # 绳桥
    ("rope", "rope ladder"),        # 绳梯
    ("rope", "skipping rope"),      # 跳绳
    ("kiss", "kiss mark"),          # 吻痕
    ("kiss", "air kiss"),           # 飞吻
    ("kiss", "kiss face"),          # 亲吻表情
    ("bond", "bond paper"),         # 债券纸张
    ("heart", "heart shape"),       # 心形
    ("heart", "heart necklace"),    # 心形项链
    ("heart", "heart earrings"),    # 心形耳环
    ("sweat", "sweatdrop"),         # 汗滴（动漫常见表情）
    ("sweat", "cold sweat"),        # 冷汗
    ("bed", "bedroom"),             # 卧室
    ("bed", "bed sheet"),           # 床单
    ("bed", "bed head"),            # 刚睡醒的头发
    ("bulge", "pocket bulge"),      # 口袋凸起
    ("bulge", "bag bulge"),         # 包凸起
    ("tent", "camping tent"),       # 露营帐篷
    ("tent", "circus tent"),        # 马戏团帐篷
    ("man", "snowman"),             # 雪人
    ("man", "fireman"),             # 消防员
    ("man", "policeman"),           # 警察
    ("man", "fisherman"),           # 渔夫
    ("man", "businessman"),         # 商人
    ("boy", "tomboy"),              # 假小子
    ("boy", "cowboy"),              # 牛仔
]

class NSFWFilter:
    """NSFW tag filter for prompts."""
    
    def __init__(self, enabled: bool = True):
        """
        Args:
            enabled: Whether NSFW filtering is enabled by default
        """
        self.enabled = enabled
        self.stats = {
            "total_processed": 0,
            "total_filtered": 0,
            "filtered_tags": {}
        }
    
    def filter_prompt(self, prompt: str, nsfw_allowed: bool = False) -> Tuple[str, List[str]]:
        """
        Filter NSFW tags from a prompt.
        
        Args:
            prompt: The prompt string to filter
            nsfw_allowed: Whether NSFW content is allowed (if True, no filtering)
            
        Returns:
            Tuple of (filtered_prompt, list_of_filtered_tags)
        """
        self.stats["total_processed"] += 1
        
        # 分割标签
        tags = [tag.strip() for tag in prompt.split(",") if tag.strip()]
        
        filtered_tags = []
        clean_tags = []
        
        for tag in tags:
            tag_lower = tag.lower()
            
            # 检查是否是男性相关词汇（始终过滤，即使 nsfw_allowed=True）
            if self._is_male_tag(tag_lower):
                filtered_tags.append(tag)
                self.stats["total_filtered"] += 1
                self.stats["filtered_tags"][tag_lower] = self.stats["filtered_tags"].get(tag_lower, 0) + 1
                # print(f"[DEBUG NSFW Filter] 过滤掉男性相关标签: '{tag}'")
                continue
            
            # 如果允许 NSFW，只过滤男性相关词汇，其他 NSFW 词汇保留
            if nsfw_allowed:
                clean_tags.append(tag)
                continue
            
            # 默认情况：过滤所有 NSFW 词汇
            if self._is_nsfw_tag(tag_lower):
                filtered_tags.append(tag)
                self.stats["total_filtered"] += 1
                self.stats["filtered_tags"][tag_lower] = self.stats["filtered_tags"].get(tag_lower, 0) + 1
                # print(f"[DEBUG NSFW Filter] 过滤掉 NSFW 标签: '{tag}'")
            else:
                clean_tags.append(tag)
        
        # 重新组合标签
        filtered_prompt = ", ".join(clean_tags)
        
        if filtered_tags:
            print(f"[DEBUG NSFW Filter] 共过滤掉 {len(filtered_tags)} 个标签")
        
        return filtered_prompt, filtered_tags

    def _is_male_tag(self, tag: str) -> bool:
        """
        判断一个标签是否与男性相关（始终过滤）
        """
        tag = tag.lower().strip()
        
        # 检查男性角色词汇
        if tag in _MALE_CHARACTER_TAGS:
            return True
        
        # 检查男性 NSFW 词汇
        if tag in _MALE_NSFW_TAGS:
            return True
        
        # 检查男性性器官词汇
        if tag in _MALE_GENITALIA_TAGS:
            return True
        
        # 部分匹配检查（避免误伤）
        male_keywords = ["male", "man", "men", "boy", "guy", "father", "dad", 
                        "son", "brother", "uncle", "grandfather", "shota"]
        
        for keyword in male_keywords:
            if keyword in tag and len(tag) < 20:  # 限制长度避免匹配长词
                # 检查安全组合
                if self._is_safe_male_combination(tag, keyword):
                    continue
                return True
        
        return False

    def _is_nsfw_tag(self, tag: str) -> bool:
        """
        判断一个标签是否为 NSFW（不包括男性相关词汇，因为这些已经单独处理）
        """
        tag = tag.lower().strip()
        
        # 精确匹配检查
        if tag in _NSFW_TAGS_LOWER:
            return True
        
        # 对于需要精确匹配的标签，不进行部分匹配
        if tag in _EXACT_MATCH_ONLY:
            return False
        
        # 部分匹配检查（对于较长的标签，避免误伤短词）
        if len(tag) > 4:  # 只对较长的标签进行部分匹配
            for nsfw_tag in _NSFW_TAGS_LOWER:
                # 避免匹配太短的词
                if len(nsfw_tag) <= 3:
                    continue
                
                # 检查是否包含 NSFW 关键词
                if nsfw_tag in tag:
                    # 排除一些安全的组合
                    if self._is_safe_combination(tag, nsfw_tag):  # 这里调用正确的方法名
                        continue
                    return True
                
                # 检查标签是否包含在 NSFW 词中（反向匹配）
                if tag in nsfw_tag and len(tag) > 3:
                    return True
        
        return False


    def _is_safe_combination(self, tag: str, nsfw_tag: str) -> bool:
        """
        检查是否为安全的组合（避免误伤）。
        例如 "breast pocket" 应该被允许，即使包含 "breast"。
        
        Args:
            tag: 完整的标签
            nsfw_tag: 匹配到的NSFW词
        
        Returns:
            True 如果是安全组合，False 否则
        """
        # 使用全局定义的 _SAFE_COMBINATIONS
        for safe_nsfw, safe_phrase in _SAFE_COMBINATIONS:
            if nsfw_tag == safe_nsfw and safe_phrase in tag.lower():
                return True
        
        return False


    def _is_safe_male_combination(self, tag: str, keyword: str) -> bool:
        """
        检查是否为安全的男性相关组合（避免误伤）
        
        Args:
            tag: 完整的标签
            keyword: 匹配到的男性关键词
        
        Returns:
            True 如果是安全组合，False 否则
        """
        safe_combinations = [
            ("man", "snowman"),
            ("man", "fireman"),
            ("man", "policeman"),
            ("man", "fisherman"),
            ("man", "businessman"),
            ("man", "postman"),
            ("man", "cameraman"),
            ("man", "handyman"),
            ("man", "superman"),
            ("man", "batman"),
            ("man", "spiderman"),
            ("boy", "tomboy"),
            ("boy", "cowboy"),
            ("boy", "paperboy"),
            ("boy", "schoolboy"),
            ("boy", "stableboy"),
            ("boy", "pageboy"),
        ]
        
        for safe_keyword, safe_phrase in safe_combinations:
            if keyword == safe_keyword and safe_phrase in tag.lower():
                return True
        
        return False
    
    def parse_command_args(self, command_text: str) -> Tuple[str, bool]:
        """
        解析命令参数，检查是否包含 --nsfw 标志。
        
        Args:
            command_text: 原始命令文本
            
        Returns:
            Tuple of (clean_command, nsfw_allowed)
        """
        # 检查是否包含 --nsfw
        if "--nsfw" in command_text:
            # 移除 --nsfw 标志
            clean_text = command_text.replace("--nsfw", "").strip()
            print(f"[DEBUG NSFW Filter] 检测到 --nsfw 参数，允许 NSFW 内容")
            return clean_text, True
        else:
            return command_text, False
    
    def get_stats(self) -> dict:
        """获取过滤统计信息"""
        return self.stats
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        self.stats = {
            "total_processed": 0,
            "total_filtered": 0,
            "filtered_tags": {}
        }
    
    def toggle_filter(self, enabled: bool = None) -> bool:
        """
        切换过滤器状态。
        
        Args:
            enabled: 如果提供，设置为指定状态；否则切换状态
            
        Returns:
            当前的过滤器状态
        """
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = not self.enabled
        
        print(f"[DEBUG NSFW Filter] 过滤器已{'启用' if self.enabled else '禁用'}")
        return self.enabled


# 创建全局单例
nsfw_filter = NSFWFilter(enabled=True)