"""Kiểm thử nhanh phần xử lý tiếng Việt (chạy: python -m unittest discover tests)."""

from __future__ import annotations

import unittest

from storytube import textutil as T


class TestNumbers(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(T.read_integer(0), "không")
        self.assertEqual(T.read_integer(5), "năm")
        self.assertEqual(T.read_integer(10), "mười")
        self.assertEqual(T.read_integer(15), "mười lăm")
        self.assertEqual(T.read_integer(21), "hai mươi mốt")
        self.assertEqual(T.read_integer(24), "hai mươi tư")
        self.assertEqual(T.read_integer(100), "một trăm")
        self.assertEqual(T.read_integer(105), "một trăm linh năm")

    def test_thousands(self):
        self.assertEqual(T.read_integer(1500), "một nghìn năm trăm")
        self.assertEqual(T.read_integer(1005), "một nghìn không trăm linh năm")
        self.assertEqual(T.read_integer(1200000), "một triệu hai trăm nghìn")

    def test_normalize_reads_numbers(self):
        out = T.normalize_for_tts("Ông ấy 62 tuổi, đi 15 km.")
        self.assertIn("sáu mươi hai", out)
        self.assertIn("mười lăm", out)
        self.assertNotIn("62", out)

    def test_percent(self):
        self.assertIn("phần trăm", T.normalize_for_tts("tăng 20%"))

    def test_abbreviation(self):
        self.assertIn("thành phố Hồ Chí Minh", T.normalize_for_tts("ở TP.HCM"))


class TestTtsText(unittest.TestCase):
    def test_strip_markdown(self):
        src = "## Chương 1\n**Đêm** ấy, *mưa* rất to."
        out = T.normalize_for_tts(src)
        self.assertNotIn("**", out)
        self.assertNotIn("##", out)
        self.assertIn("Đêm", out)

    def test_sentences(self):
        out = T.sentences("Một. Hai! Ba?")
        self.assertEqual(len(out), 3)

    def test_chunk_long(self):
        text = "Câu một rất dài. " * 20
        chunks = T.chunk_text(text, 200)
        self.assertTrue(all(len(c) <= 260 for c in chunks))

    def test_estimate_grows(self):
        short = T.estimate_speech_ms("Một hai ba.")
        long = T.estimate_speech_ms("Một hai ba bốn năm sáu bảy tám chín mười.")
        self.assertGreater(long, short)


class TestTiming(unittest.TestCase):
    def test_word_timings_cover_duration(self):
        words = T.word_timings("Đêm thứ ba mưa không tắt", 4000)
        self.assertEqual(len(words), 6)
        self.assertEqual(words[0]["s"], 0)
        self.assertEqual(words[-1]["e"], 4000)
        for a, b in zip(words, words[1:]):
            self.assertGreaterEqual(b["s"], a["e"])

    def test_caption_pages_balanced(self):
        words = [{"w": f"w{i}", "s": i * 200, "e": (i + 1) * 200} for i in range(10)]
        pages = T.caption_pages(words, max_words=4, max_chars=80)
        self.assertTrue(all(len(p) <= 4 for p in pages))
        self.assertGreaterEqual(len(pages[-1]), 2)

    def test_ass_time(self):
        self.assertEqual(T.ass_time(0), "0:00:00.00")
        self.assertEqual(T.ass_time(3661230), "1:01:01.23")


class TestSlug(unittest.TestCase):
    def test_vietnamese(self):
        self.assertEqual(T.slugify("Người giữ đèn biển"), "nguoi-giu-den-bien")


if __name__ == "__main__":
    unittest.main()
