"""Kiểm thử gộp cấu hình: lưu key này không được xoá key kia."""

from __future__ import annotations

import unittest

from storytube.api import api, merge_settings

BASE = {
    "llm": {
        "default": "deepseek",
        "providers": {
            "deepseek": {
                "base_url": "https://api.deepseek.com/anthropic",
                "model": "deepseek-chat",
                "api_key": "sk-deepseek",
            },
            "openai": {"api_key": ""},
        },
    },
    "tts": {
        "default_profile": "nam-tram-eleven",
        "providers": {
            "elevenlabs": {"api_key": "sk_eleven", "model": "eleven_v3"},
            "fpt": {"api_key": "fpt-key"},
        },
    },
    "images": {"providers": {"elevenlabs": {"api_key": "sk_eleven"}}},
}


class TestMergeSettings(unittest.TestCase):
    def test_saving_llm_keeps_tts_key(self):
        incoming = {
            "llm": {"default": "deepseek",
                    "providers": {"deepseek": {"base_url": "https://api.deepseek.com/anthropic",
                                               "model": "deepseek-chat"}}},
            "tts": {"providers": {"elevenlabs": {}, "fpt": {}, "azure": {}}},
        }
        out = merge_settings(BASE, incoming)
        self.assertEqual(out["llm"]["providers"]["deepseek"]["api_key"], "sk-deepseek")
        self.assertEqual(out["tts"]["providers"]["elevenlabs"]["api_key"], "sk_eleven")
        self.assertEqual(out["images"]["providers"]["elevenlabs"]["api_key"], "sk_eleven")

    def test_saving_tts_keeps_llm_key(self):
        incoming = {"tts": {"providers": {"elevenlabs": {"api_key": "sk_new"}}}}
        out = merge_settings(BASE, incoming)
        self.assertEqual(out["llm"]["providers"]["deepseek"]["api_key"], "sk-deepseek")
        self.assertEqual(out["tts"]["providers"]["elevenlabs"]["api_key"], "sk_new")
        # field khác của provider không bị mất
        self.assertEqual(out["tts"]["providers"]["elevenlabs"]["model"], "eleven_v3")

    def test_empty_or_masked_key_never_overwrites(self):
        for value in ("", "***", None):
            out = merge_settings(BASE, {"tts": {"providers": {"elevenlabs": {"api_key": value}}}})
            self.assertEqual(out["tts"]["providers"]["elevenlabs"]["api_key"], "sk_eleven")

    def test_deep_merge_keeps_siblings(self):
        out = merge_settings(BASE, {"llm": {"providers": {"deepseek": {"temperature": 0.5}}}})
        provider = out["llm"]["providers"]["deepseek"]
        self.assertEqual(provider["temperature"], 0.5)
        self.assertEqual(provider["model"], "deepseek-chat")
        self.assertEqual(provider["api_key"], "sk-deepseek")

    def test_new_provider_added(self):
        out = merge_settings(BASE, {"llm": {"providers": {"custom": {"base_url": "http://x/v1"}}}})
        self.assertEqual(out["llm"]["providers"]["custom"]["base_url"], "http://x/v1")
        self.assertEqual(out["llm"]["providers"]["deepseek"]["api_key"], "sk-deepseek")


class TestRoutes(unittest.TestCase):
    def test_beat_routes_exist(self):
        for method, path in [
            ("POST", "/api/beats/b1/write"),
            ("POST", "/api/beats/b1/polish"),
            ("POST", "/api/chapters/c1/beats"),
            ("POST", "/api/scenes/s1/image"),
            ("POST", "/api/videos/v1/images"),
            ("POST", "/api/projects/p1/ai/premise"),
        ]:
            handler, params = api.dispatch(method, path)
            self.assertIsNotNone(handler, f"thiếu route {method} {path}")


class TestCleanProse(unittest.TestCase):
    def test_unwraps_json_object(self):
        from storytube.story import clean_prose

        raw = '{"content": "Đêm ấy, trời mưa rất to."}'
        self.assertEqual(clean_prose(raw), "Đêm ấy, trời mưa rất to.")

    def test_strips_code_fence(self):
        from storytube.story import clean_prose

        self.assertEqual(clean_prose("```\nMột đoạn văn.\n```"), "Một đoạn văn.")

    def test_keeps_plain_text(self):
        from storytube.story import clean_prose

        text = "Hắn mở cửa. Gió lùa vào."
        self.assertEqual(clean_prose(text), text)


if __name__ == "__main__":
    unittest.main()
