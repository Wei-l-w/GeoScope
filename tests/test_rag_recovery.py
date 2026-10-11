"""RAG 缓存恢复回归：仅用内存语料和临时索引，不调用 API 或真实数据库。"""

import pickle
import warnings
from unittest.mock import Mock

import pytest
import sklearn
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.feature_extraction.text import TfidfVectorizer

from agent import rag


@pytest.fixture()
def isolated_index(tmp_path, monkeypatch):
    path = tmp_path / "rag_index.pkl"
    corpus = [
        rag.Chunk("news_articles", "1", "Houthi attack", "Houthi attack on merchant vessel",
                  "", "2026-01-01"),
        rag.Chunk("acled_events", "2", "Port protest", "Port workers protest over wages",
                  "", "2026-01-02"),
    ]
    loader = Mock(return_value=corpus)
    monkeypatch.setattr(rag, "INDEX_PATH", path)
    monkeypatch.setattr(rag, "load_corpus", loader)
    return path, loader


def test_missing_index_builds_and_valid_cache_is_reused(isolated_index):
    path, loader = isolated_index
    first = rag.RagIndex.load()
    assert first.search("Houthi attack")[0][0].ref_id == "1"
    assert path.is_file()
    original = path.read_bytes()
    second = rag.RagIndex.load()
    assert second.search("Port workers")[0][0].ref_id == "2"
    assert second.metadata["sklearn_version"] == sklearn.__version__
    assert path.read_bytes() == original
    loader.assert_called_once_with()


@pytest.mark.parametrize("bad_bytes", [b"", b"not a pickle", b"\x80\xff"])
def test_corrupt_or_truncated_cache_rebuilds(isolated_index, bad_bytes):
    path, loader = isolated_index
    path.write_bytes(bad_bytes)
    assert rag.RagIndex.load().search("Houthi attack")
    loader.assert_called_once_with()
    assert isinstance(pickle.loads(path.read_bytes()), rag.RagIndex)


@pytest.mark.parametrize("problem", ["legacy", "version", "unfitted", "wrong_shape", "wrong_type"])
def test_unusable_loaded_index_rebuilds(isolated_index, problem):
    path, loader = isolated_index
    idx = rag.RagIndex()
    idx.build()
    loader.reset_mock()
    if problem == "legacy":
        del idx.metadata
    elif problem == "version":
        idx.metadata["sklearn_version"] = "0.0.0"
    elif problem == "unfitted":
        idx.vectorizer = TfidfVectorizer()
    elif problem == "wrong_shape":
        idx.matrix = idx.matrix[:, :-1]
    else:
        idx = {"unexpected": "payload"}
    path.write_bytes(pickle.dumps(idx))
    rebuilt = rag.RagIndex.load()
    assert rebuilt.search("Houthi attack")[0][0].ref_id == "1"
    loader.assert_called_once_with()


def test_sklearn_version_warning_rebuilds(isolated_index, monkeypatch):
    path, loader = isolated_index
    path.write_bytes(b"placeholder")

    def incompatible_load(_file):
        warnings.warn(InconsistentVersionWarning(
            estimator_name="TfidfVectorizer", current_sklearn_version=sklearn.__version__,
            original_sklearn_version="0.0.0"))
        pytest.fail("版本告警应中断旧缓存加载")

    monkeypatch.setattr(rag.pickle, "load", incompatible_load)
    assert rag.RagIndex.load().search("Houthi attack")
    loader.assert_called_once_with()


def test_loading_always_checks_transform(isolated_index, monkeypatch):
    rag.RagIndex().build()
    transform = TfidfVectorizer.transform
    calls = []

    def tracked_transform(self, values):
        calls.append(values)
        return transform(self, values)

    monkeypatch.setattr(TfidfVectorizer, "transform", tracked_transform)
    rag.RagIndex.load()
    assert calls == [["index validation"]]


def test_interrupted_save_preserves_previous_cache(isolated_index, monkeypatch):
    path, _ = isolated_index
    rag.RagIndex().build()
    original = path.read_bytes()

    def failed_dump(_idx, file, **_kwargs):
        file.write(b"partial pickle")
        raise OSError("simulated disk failure")

    monkeypatch.setattr(rag.pickle, "dump", failed_dump)
    with pytest.raises(OSError, match="simulated disk failure"):
        rag.RagIndex().build()
    assert path.read_bytes() == original
    assert list(path.parent.glob(".rag_index.pkl.*.tmp")) == []


def test_permission_error_is_not_hidden_or_rebuilt(isolated_index, monkeypatch):
    _, loader = isolated_index

    def denied_open(*_args, **_kwargs):
        raise PermissionError("simulated access denied")

    monkeypatch.setattr(rag, "open", denied_open, raising=False)
    with pytest.raises(PermissionError, match="simulated access denied"):
        rag.RagIndex.load()
    loader.assert_not_called()


def test_failed_rebuild_does_not_replace_old_cache(isolated_index):
    path, loader = isolated_index
    path.write_bytes(b"old cache")
    loader.side_effect = RuntimeError("simulated database failure")
    with pytest.raises(RuntimeError, match="simulated database failure"):
        rag.RagIndex.load()
    assert path.read_bytes() == b"old cache"


def test_unexpected_transform_error_propagates(isolated_index, monkeypatch):
    _, loader = isolated_index
    rag.RagIndex().build()
    loader.reset_mock()

    def failed_transform(*_args, **_kwargs):
        raise RuntimeError("unexpected runtime failure")

    monkeypatch.setattr(TfidfVectorizer, "transform", failed_transform)
    with pytest.raises(RuntimeError, match="unexpected runtime failure"):
        rag.RagIndex.load()
    loader.assert_not_called()
