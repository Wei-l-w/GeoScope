"""测试产物隔离，避免覆盖正在使用的地图输出和知识库索引。"""

import pytest


@pytest.fixture(autouse=True)
def isolated_artifacts(tmp_path, monkeypatch):
    from agent import artifacts, model_config, rag, tools

    monkeypatch.setattr(tools, "OUTPUT_DIR", tmp_path / "geojson")
    monkeypatch.setattr(artifacts, "OUTPUT_DIR", tmp_path / "geojson")
    monkeypatch.setattr(rag, "INDEX_PATH", tmp_path / "rag_index.pkl")
    # 开发机上可能真的保存过模型配置：不隔离的话，模型名、来源标签会随机器变化
    monkeypatch.setattr(model_config, "SETTINGS_PATH", tmp_path / "model_settings.json")
