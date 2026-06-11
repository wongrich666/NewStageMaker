from __future__ import annotations

import unittest

from workflow_code_skeleton.app.utils.user_visible_text import (
    export_safe_text,
    has_meaningful_content,
    is_machine_structured_content,
    is_meaningful_text,
    is_placeholder_text,
)


class UserVisibleTextTests(unittest.TestCase):
    def test_placeholder_marker_is_not_meaningful(self) -> None:
        value = "【待补全：补充人物定位】"

        self.assertTrue(is_placeholder_text(value))
        self.assertFalse(is_meaningful_text(value))
        self.assertFalse(has_meaningful_content(value))

    def test_section_title_only_is_not_meaningful(self) -> None:
        value = "人物小传"

        self.assertTrue(is_placeholder_text(value))
        self.assertFalse(is_meaningful_text(value))

    def test_multiline_text_with_one_placeholderish_line_remains_meaningful(self) -> None:
        value = (
            "每个角色都必须在高压制度里显出自己的生存姿态。\n"
            "未提供联网参考，本轮仅基于世界观生成。\n"
            "林夏：主角，在城市里努力保住工作与尊严。"
        )

        self.assertFalse(is_placeholder_text(value))
        self.assertTrue(is_meaningful_text(value))
        self.assertTrue(has_meaningful_content(value))

    def test_export_safe_text_converts_json_like_text_instead_of_leaking_raw_json(self) -> None:
        value = '{"top":"red shirt","bottom":"jeans"}'

        self.assertTrue(is_machine_structured_content(value))
        text = export_safe_text(value)
        self.assertIn("red shirt", text)
        self.assertIn("jeans", text)
        self.assertNotIn("{", text)
        self.assertNotIn("}", text)

    def test_export_safe_text_summarizes_python_dict_literal_instead_of_str_dict(self) -> None:
        value = "{'服装版本映射内容': {'alias_name': '林夏【会议室交锋态】', 'usage_rule': '高压对峙时使用'}}"

        self.assertTrue(is_machine_structured_content(value))
        text = export_safe_text(value)
        self.assertIn("林夏【会议室交锋态】", text)
        self.assertIn("高压对峙时使用", text)
        self.assertNotIn("{", text)
        self.assertNotIn("}", text)
        self.assertNotEqual(text, value)


if __name__ == "__main__":
    unittest.main()
