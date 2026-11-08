"""Kiểm thử lớp LLM bằng một server giả lập OpenAI (không cần API key)."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from storytube import llm

REPLY = {
    "id": "x",
    "model": "stub-model",
    "choices": [{"message": {"role": "assistant", "content": json.dumps({
        "title": "Người giữ đèn biển",
        "logline": "Một người giữ hải đăng viết thay lá thư của người đã mất.",
        "scenes": [{"narration": "Đêm thứ ba, mưa không tắt.", "on_screen": "Đêm thứ ba"}],
    }, ensure_ascii=False)}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 40},
}


class Handler(BaseHTTPRequestHandler):
    last_payload: dict = {}
    last_headers: dict = {}
    last_path: str = ""
    wire: str = "openai"

    def log_message(self, *args):  # noqa: A003
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        Handler.last_payload = json.loads(self.rfile.read(length) or b"{}")
        Handler.last_headers = {k.lower(): v for k, v in self.headers.items()}
        Handler.last_path = self.path
        if Handler.wire == "anthropic":
            reply = {
                "id": "msg_1",
                "model": "deepseek-chat",
                "content": [{"type": "text", "text": json.dumps(
                    {"title": "Người giữ đèn biển"}, ensure_ascii=False)}],
                "usage": {"input_tokens": 88, "output_tokens": 22},
                "stop_reason": "end_turn",
            }
        else:
            reply = REPLY
        body = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def cfg_for(port: int, wire: str = "openai") -> dict:
    # base_url giống thật: anthropic dùng gốc không có /v1 (DeepSeek: .../anthropic)
    base = f"http://127.0.0.1:{port}" + ("" if wire == "anthropic" else "/v1")
    provider = {
        "base_url": base,
        "api_key": "test",
        "model": "stub-model",
        "temperature": 0.7,
        "max_tokens": 512,
        "json_mode": True,
    }
    if wire == "anthropic":
        provider["api_style"] = "anthropic"
        provider["model"] = "deepseek-chat"
    return {
        "llm": {
            "default": "stub",
            "providers": {"stub": provider},
        }
    }


class TestLLM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_chat_json_roundtrip(self):
        Handler.wire = "openai"
        data, res = llm.chat_json(
            [{"role": "user", "content": "kịch bản"}],
            cfg=cfg_for(self.port), provider="stub",
        )
        self.assertEqual(data["title"], "Người giữ đèn biển")
        self.assertEqual(res["usage"]["prompt"], 120)
        self.assertEqual(res["model"], "stub-model")
        self.assertEqual(Handler.last_payload["model"], "stub-model")
        self.assertEqual(Handler.last_payload["response_format"], {"type": "json_object"})

    def test_anthropic_wire(self):
        """DeepSeek đi qua /anthropic: tách system, header x-api-key, parse content[].text."""
        Handler.wire = "anthropic"
        cfg = cfg_for(self.port, "anthropic")
        data, res = llm.chat_json(
            [{"role": "system", "content": "Bạn là biên kịch"},
             {"role": "user", "content": "viết đi"}],
            cfg=cfg, provider="stub",
        )
        self.assertEqual(data["title"], "Người giữ đèn biển")
        self.assertEqual(res["usage"]["prompt"], 88)
        self.assertEqual(res["usage"]["completion"], 22)
        self.assertEqual(Handler.last_payload["system"], "Bạn là biên kịch")
        self.assertEqual(len(Handler.last_payload["messages"]), 1)
        self.assertEqual(Handler.last_headers.get("x-api-key"), "test")
        self.assertEqual(Handler.last_headers.get("anthropic-version"), "2023-06-01")
        self.assertEqual(Handler.last_path, "/v1/messages")
        Handler.wire = "openai"

    def test_extract_json_variants(self):
        self.assertEqual(llm.extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm.extract_json('Đây là kết quả: {"a": [1, 2]} nhé'), {"a": [1, 2]})
        with self.assertRaises(llm.LLMError):
            llm.extract_json("không có json")

    def test_missing_key_is_clear_error(self):
        cfg = cfg_for(self.port)
        cfg["llm"]["providers"]["stub"]["api_key"] = ""
        cfg["llm"]["providers"]["stub"]["base_url"] = "https://api.example.com/v1"
        with self.assertRaises(llm.LLMError) as ctx:
            llm.chat([{"role": "user", "content": "x"}], cfg=cfg, provider="stub")
        self.assertIn("API key", str(ctx.exception))

    def test_is_ready(self):
        self.assertTrue(llm.is_ready(cfg_for(self.port)))
        cfg = cfg_for(self.port)
        cfg["llm"]["providers"]["stub"]["api_key"] = ""
        cfg["llm"]["providers"]["stub"]["base_url"] = "https://api.example.com/v1"
        self.assertFalse(llm.is_ready(cfg))


if __name__ == "__main__":
    unittest.main()
