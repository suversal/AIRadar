from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.digest_filter import is_digest_title


class DigestTitleTests(unittest.TestCase):
    """真实标题取自本库，四个信源各自的合集格式都不一样。"""

    def test_slash_separated_digest(self):
        self.assertTrue(
            is_digest_title(
                "早报｜宇树「超人」原地跳高2米/小米SU7系列交付突破50万台/豆包支持手机远程操作电脑"
            )
        )

    def test_semicolon_digest_with_a_date_after_the_column_name(self):
        """IT之家的格式在栏目名和冒号之间夹了日期。"""
        self.assertTrue(
            is_digest_title(
                "IT早报 0816：DeepSeek V4 Pro 正式版、Harness 上线国家超算互联网；"
                "番茄小说作者“去世”三年后“复活”；曝小米"
            )
        )

    def test_full_width_pipe_with_prefixed_column_name(self):
        self.assertTrue(
            is_digest_title(
                "氪星晚报｜英特尔将在数据中心部门裁员；日产在美召回超16万辆；我国将建设3000个电动重卡充换电站"
            )
        )

    def test_enumeration_comma_counts_as_a_separator(self):
        self.assertTrue(
            is_digest_title("派早报：Meta 被诉借助 AI 违规裁员、Google 被诉使用版权内容训练 Gemini 模型等")
        )


class NotDigestTests(unittest.TestCase):
    """栏目标签本身不构成合集——这几条必须留下来。"""

    def test_single_story_under_a_column_label(self):
        """量子位的「快讯｜」是栏目标签，后面就一条新闻。"""
        self.assertFalse(is_digest_title("快讯｜范式PhanRouter上线智谱GLM-5.3，即日开放调用"))

    def test_column_word_inside_a_company_name(self):
        """「圆通速递」里的"速递"是公司名，不是栏目。"""
        self.assertFalse(is_digest_title("圆通速递：6月快递产品收入58.83亿元，同比增长6.44%"))

    def test_chinese_comma_is_not_a_separator(self):
        """单条新闻的标题里全是逗号，把它当分隔符会误杀一大片。"""
        self.assertFalse(
            is_digest_title("快讯｜阿里发布Qwen3.8-27B，支持262K上下文，性能超越前代")
        )

    def test_ordinary_headline_without_a_column_label(self):
        self.assertFalse(
            is_digest_title("如何禁用或避免侵入式 AI：一份覆盖 Windows、Chrome、Edge、Firefox 的实用指南")
        )

    def test_column_word_appearing_late_in_the_title_is_ignored(self):
        """前缀限长 4 字，防止正文里出现的"快讯""要闻"把普通新闻拖下水。"""
        self.assertFalse(
            is_digest_title("某公司宣布上线全新的企业级新闻快讯：支持多端推送、离线阅读")
        )

    def test_empty_and_none(self):
        self.assertFalse(is_digest_title(""))
        self.assertFalse(is_digest_title(None))


if __name__ == "__main__":
    unittest.main()
