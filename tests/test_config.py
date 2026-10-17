import importlib
import os

from dotenv import load_dotenv

from verifier import config


def test_env_file_points_at_repo_root():
    assert config.ENV_FILE.name == ".env"
    assert (config.ENV_FILE.parent / "pyproject.toml").is_file()


def test_require_env_raises_keyerror_with_the_name():
    try:
        config.require_env("VERIFIER_DEFINITELY_UNSET")
    except KeyError as e:
        assert "VERIFIER_DEFINITELY_UNSET" in str(e)
    else:
        raise AssertionError("expected KeyError")


def test_blank_values_count_as_unset(monkeypatch):
    monkeypatch.setenv("VERIFIER_BLANK_PROBE", "   ")
    assert config.optional_env("VERIFIER_BLANK_PROBE") is None
    assert config.int_env("VERIFIER_BLANK_PROBE", 7) == 7


def test_shell_env_wins_over_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("VERIFIER_PROVIDER=from_file\n", encoding="utf-8")
    monkeypatch.setenv("VERIFIER_PROVIDER", "from_shell")
    load_dotenv(env_file, override=False)
    assert os.environ["VERIFIER_PROVIDER"] == "from_shell"


def test_provider_default_is_anthropic_and_env_is_case_insensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIFIER_ENV_FILE", str(tmp_path / "absent.env"))  # ignore the real .env
    monkeypatch.delenv("VERIFIER_PROVIDER", raising=False)
    importlib.reload(config)
    assert config.provider() == "anthropic"
    monkeypatch.setenv("VERIFIER_PROVIDER", "OpenAI")
    assert config.provider() == "openai"
    monkeypatch.undo()
    importlib.reload(config)
    assert config.ENV_FILE.name == ".env"


def test_provider_specific_base_url_beats_the_generic_one(monkeypatch):
    """Switching VERIFIER_PROVIDER must not let a stale VERIFIER_BASE_URL hijack the request."""
    monkeypatch.setenv("VERIFIER_BASE_URL", "https://generic.example/v1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://anthropic.example")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    assert config.anthropic_base_url() == "https://anthropic.example"
    assert config.openai_base_url() == "https://openai.example/v1"
    monkeypatch.delenv("ANTHROPIC_BASE_URL")
    monkeypatch.delenv("OPENAI_BASE_URL")
    assert config.anthropic_base_url() == "https://generic.example/v1"
    assert config.openai_base_url() == "https://generic.example/v1"


def test_extra_body_must_be_a_json_object(monkeypatch):
    monkeypatch.delenv("VERIFIER_EXTRA_BODY", raising=False)  # the shipped .env sets it
    assert config.extra_body() == {}
    monkeypatch.setenv("VERIFIER_EXTRA_BODY", '{"thinking":{"type":"disabled"}}')
    assert config.extra_body() == {"thinking": {"type": "disabled"}}
    monkeypatch.setenv("VERIFIER_EXTRA_BODY", "not json")
    try:
        config.extra_body()
    except ValueError as e:
        assert "VERIFIER_EXTRA_BODY" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_openai_endpoint_inferred_from_which_key_is_present(monkeypatch):
    monkeypatch.delenv("VERIFIER_API_KEY", raising=False)
    monkeypatch.delenv("VERIFIER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-probe")
    assert config.openai_api_key() == "sk-deepseek-probe"
    assert config.openai_base_url() == "https://api.deepseek.com/v1"
    monkeypatch.setenv("VERIFIER_BASE_URL", "http://localhost:1234/v1/")
    assert config.openai_base_url() == "http://localhost:1234/v1"


def test_openai_api_key_missing_is_a_keyerror(monkeypatch):
    for name in ("VERIFIER_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    try:
        config.openai_api_key()
    except KeyError as e:
        assert "VERIFIER_API_KEY" in str(e)
    else:
        raise AssertionError("expected KeyError")


def test_describe_has_no_secret():
    info = config.describe()
    assert set(info) == {"provider", "model", "prompt_version", "api_key_set", "base_url_set", "env_file"}
    assert all("sk-" not in str(v) for v in info.values())
