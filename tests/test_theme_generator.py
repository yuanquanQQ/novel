import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from engine.theme_generator import (
    ThemeConfigurationError,
    ThemeGenerationError,
    generate_themes,
    parse_theme_response,
)
import server.app as server_app


def _options():
    return [
        {
            "title": f"测试故事{i}",
            "id": f"test-story-{i}",
            "genre": "悬疑",
            "description": f"第{i}个故事简介",
            "chapter_count": 80 + i,
            "words_per_chapter": 3000,
            "theme": "信任与选择",
            "conflict": f"主角必须解决第{i}个困局",
        }
        for i in range(1, 4)
    ]


class ThemeGeneratorTests(unittest.TestCase):
    def test_generate_uses_environment_and_openai_json_mode(self):
        content = json.dumps({"options": _options()}, ensure_ascii=False)
        create = Mock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        ))
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        ))

        with patch("engine.theme_generator.OpenAI", return_value=client) as openai:
            result = generate_themes(
                "雨夜里的旧车站", "悬疑", "悬疑推理",
                environ={
                    "DEEPSEEK_API_KEY": "secret",
                    "DEEPSEEK_BASE_URL": "https://example.test/v1",
                    "THEME_MODEL": "theme-model",
                },
            )

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["title"], "测试故事1")
        openai.assert_called_once_with(
            api_key="secret", base_url="https://example.test/v1"
        )
        request = create.call_args.kwargs
        self.assertEqual(request["model"], "theme-model")
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertIn("雨夜里的旧车站", request["messages"][1]["content"])
        self.assertIn("创作方向：悬疑推理", request["messages"][1]["content"])

    def test_generate_uses_root_env_when_environ_is_omitted(self):
        content = json.dumps({"options": _options()}, ensure_ascii=False)
        create = Mock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        ))
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        ))
        with patch("engine.theme_generator.load_env", return_value={
            "API_KEY": "root-key", "API_BASE_URL": "https://root.example/v1",
            "THEME_MODEL": "root-theme",
        }), patch("engine.theme_generator.OpenAI", return_value=client) as openai:
            generate_themes("", "", "自由创作", client=client)
        openai.assert_not_called()
        self.assertEqual(create.call_args.kwargs["model"], "root-theme")

    def test_missing_or_placeholder_key_has_clear_error(self):
        for environ in ({}, {"API_KEY": ""}, {"API_KEY": "your-api-key-here"}):
            with self.subTest(environ=environ):
                with self.assertRaisesRegex(
                    ThemeConfigurationError, "API_KEY 或 DEEPSEEK_API_KEY"
                ):
                    generate_themes(direction="自由创作", environ=environ)

    def test_invalid_and_duplicate_ids_receive_unique_safe_fallbacks(self):
        options = _options()
        options[0]["id"] = "中文 ID"
        options[1]["id"] = "same-id"
        options[2]["id"] = "same-id"
        parsed = parse_theme_response(json.dumps({"options": options}, ensure_ascii=False))
        ids = [item["id"] for item in parsed]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(ids[0].startswith("story-"))
        self.assertEqual(ids[1], "same-id")
        self.assertTrue(ids[2].startswith("story-"))

    def test_parser_rejects_wrong_shape_and_types(self):
        with self.assertRaisesRegex(ThemeGenerationError, "恰好 3 个"):
            parse_theme_response(json.dumps({"options": _options()[:2]}))
        invalid = _options()
        invalid[0]["chapter_count"] = "100"
        with self.assertRaisesRegex(ThemeGenerationError, "chapter_count"):
            parse_theme_response(json.dumps({"options": invalid}, ensure_ascii=False))


class ThemeGeneratorAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server_app.app)

    def test_api_returns_suggestions_without_creating(self):
        options = _options()
        with patch.object(server_app, "generate_themes", return_value=options) as generate:
            response = self.client.post(
                "/api/novel-themes/generate",
                json={"inspiration": "逆行列车", "genre": "科幻", "direction": "科幻未来"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"options": options})
        generate.assert_called_once_with("逆行列车", "科幻", "科幻未来")

    def test_api_maps_configuration_and_generation_errors(self):
        cases = [
            (ThemeConfigurationError("缺少密钥"), 400),
            (ThemeGenerationError("响应无效"), 502),
        ]
        for error, status in cases:
            with self.subTest(status=status), patch.object(
                server_app, "generate_themes", side_effect=error
            ):
                response = self.client.post(
                    "/api/novel-themes/generate", json={"direction": "自由创作"}
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["detail"], str(error))

    def test_api_requires_and_validates_direction(self):
        missing = self.client.post("/api/novel-themes/generate", json={})
        self.assertEqual(missing.status_code, 422)
        invalid = self.client.post(
            "/api/novel-themes/generate", json={"direction": "不存在"}
        )
        self.assertEqual(invalid.status_code, 422)

    def test_api_validates_input_lengths(self):
        response = self.client.post(
            "/api/novel-themes/generate",
            json={"inspiration": "x" * 1001, "genre": ""},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
