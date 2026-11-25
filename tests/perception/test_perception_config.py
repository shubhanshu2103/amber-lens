from pathlib import Path

from amber_lens.perception.config import (
    DEFAULT_OLLAMA_HOST,
    DEFAULT_VISION_MODEL,
    load_settings,
    settings_from_mapping,
)


def test_defaults_resolve_against_root(tmp_path: Path) -> None:
    settings = settings_from_mapping({}, root=tmp_path)
    assert settings.data_dir == (tmp_path / "../amber-lens-data/data").resolve()
    assert settings.cache_dir == (tmp_path / ".cache/perception").resolve()
    assert settings.ollama_host == DEFAULT_OLLAMA_HOST
    assert settings.vision_model == DEFAULT_VISION_MODEL == "qwen2.5vl:7b"


def test_absolute_paths_and_model_are_kept(tmp_path: Path) -> None:
    data = tmp_path / "somewhere"
    settings = settings_from_mapping(
        {"AMBER_DATA_DIR": str(data), "VISION_MODEL_NAME": " qwen2.5vl:3b "}, root=tmp_path
    )
    assert settings.data_dir == data
    assert settings.vision_model == "qwen2.5vl:3b"


def test_host_without_scheme_gets_http_and_loses_trailing_slash(tmp_path: Path) -> None:
    settings = settings_from_mapping({"OLLAMA_HOST": "127.0.0.1:11434/"}, root=tmp_path)
    assert settings.ollama_host == "http://127.0.0.1:11434"


def test_blank_model_means_default(tmp_path: Path) -> None:
    assert settings_from_mapping({"VISION_MODEL_NAME": "  "}, root=tmp_path).vision_model == DEFAULT_VISION_MODEL


def test_process_env_wins_over_dotenv(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("AMBER_DATA_DIR=from_file\nVISION_MODEL_NAME=file-model\n", encoding="utf-8")
    monkeypatch.setenv("VISION_MODEL_NAME", "env-model")
    monkeypatch.delenv("AMBER_DATA_DIR", raising=False)
    settings = load_settings(root=tmp_path)
    assert settings.vision_model == "env-model"
    assert settings.data_dir == (tmp_path / "from_file").resolve()


def test_missing_dotenv_is_fine(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AMBER_CACHE_DIR", raising=False)
    assert load_settings(root=tmp_path).cache_dir == (tmp_path / ".cache/perception").resolve()
