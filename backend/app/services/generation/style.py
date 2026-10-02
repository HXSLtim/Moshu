"""文风分析服务

提供对用户上传的文风样本文本进行简单的句式与描写风格分析，输出特征标签列表。
"""
from typing import List


class StyleService:
    """文风分析服务类"""

    def analyze_style(self, text: str) -> List[str]:
        """分析文风特征，返回特征标签列表"""
        features: List[str] = []

        if not text:
            return features

        sample_text = text[-500:] if len(text) > 500 else text

        # 统计句子长度和结构
        sentences = (
            sample_text.replace("。", "。\n")
            .replace("！", "！\n")
            .replace("？", "？\n")
            .split("\n")
        )
        sentences = [s.strip() for s in sentences if s.strip()]

        if sentences:
            avg_length = sum(len(s) for s in sentences) / len(sentences)

            if avg_length < 15:
                features.append("使用简短有力的句式")
            elif avg_length > 30:
                features.append("使用细腻详尽的长句描写")
            else:
                features.append("使用长短句结合的叙事方式")

        # 检测描写风格
        if "，" in sample_text and sample_text.count("，") > len(sample_text) / 50:
            features.append("善用逗号进行细节铺陈")

        if any(word in sample_text for word in ["只见", "但见", "忽见", "忽听", "忽闻"]):
            features.append("采用古典小说的叙事手法")

        if any(word in sample_text for word in ["心中", "心想", "暗道", "暗想"]):
            features.append("注重心理描写")

        return features


style_service = StyleService()
