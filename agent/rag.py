"""RAG 空间知识库（M3）：新闻正文 + ACLED 事件描述 -> 可检索知识块。

架构说明（面试可讲）：
- 检索接口为标准「embed -> 向量 -> 余弦相似 top-k」，与稠密向量方案完全同构；
- 当前嵌入端点为 TF-IDF 稀疏向量（scikit-learn），原因：所用 LLM 代理无
  /embeddings 端点。更换模型需要适配 RagIndex 的构建、检索与持久化；
- 跨语言问题用「LLM 查询改写」解决：语料为英文，Agent 被引导用英文关键词检索。

重建索引：
    python -m agent.rag --rebuild
"""

from __future__ import annotations

import logging
import os
import pickle
import re
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config, db

INDEX_PATH = config.ROOT / "data" / "rag_index.pkl"
_CHUNK_SIZE = 600   # 字符数，新闻正文切块
_CHUNK_OVERLAP = 100
_TOP_K = 5
_MIN_SCORE = 0.05   # 低于此相似度视为不相关，防幻觉引用
_INDEX_FORMAT_VERSION = 1
_LOG = logging.getLogger(__name__)


class _InvalidIndex(ValueError):
    """缓存无法检索；可从数据库重新生成，不用于表示文件系统错误。"""


@dataclass
class Chunk:
    source_table: str   # news_articles / acled_events
    ref_id: str         # 原文主键（新闻 id / 事件 event_id）
    title: str
    text: str
    url: str
    date: str


# ---------------- 语料抽取 ----------------

def _split_text(text: str) -> list[str]:
    """按段落优先、定长兜底切块，块间保留重叠防语义截断。"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        cut = text.rfind(". ", start + _CHUNK_SIZE // 2, end)  # 尽量在句号处断开
        if cut > start:
            end = cut + 1
        chunks.append(text[start:end])
        start = end - _CHUNK_OVERLAP if end < len(text) else len(text)
    return chunks


def load_corpus() -> list[Chunk]:
    chunks: list[Chunk] = []
    with db.connect() as con:
        news = con.execute(
            "SELECT id, title, body, url, published_at FROM news_articles "
            "WHERE body IS NOT NULL AND LENGTH(body) > 200"
        ).fetchall()
        for nid, title, body, url, ts in news:
            for i, piece in enumerate(_split_text(body)):
                chunks.append(Chunk("news_articles", str(nid), f"{title} [片段{i+1}]",
                                    piece, url or "", str(ts or "")))
        events = con.execute(
            "SELECT event_id, event_type || ' @ ' || location || ', ' || country, "
            "notes, '', event_date FROM acled_events "
            "WHERE notes IS NOT NULL AND LENGTH(notes) > 30"
        ).fetchall()
        for eid, title, notes, _, dt in events:
            chunks.append(Chunk("acled_events", str(eid), title, notes, "", str(dt or "")))
    return chunks


# ---------------- 索引构建与检索 ----------------

class RagIndex:
    """向量索引：TF-IDF 稀疏矩阵 + 语料元数据，pickle 持久化。"""

    def __init__(self):
        self.vectorizer = None
        self.matrix = None
        self.chunks: list[Chunk] = []
        self.metadata: dict = {}

    def build(self) -> int:
        import sklearn
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.chunks = load_corpus()
        if not self.chunks:
            raise RuntimeError("语料为空：请先入库 news / acled 数据")
        self.vectorizer = TfidfVectorizer(max_features=30000, ngram_range=(1, 2),
                                          stop_words="english")
        self.matrix = self.vectorizer.fit_transform(c.text for c in self.chunks)
        self.metadata = {
            "format_version": _INDEX_FORMAT_VERSION,
            "sklearn_version": sklearn.__version__,
        }
        self._validate()
        self._save()
        return len(self.chunks)

    def _save(self) -> None:
        """同目录写完并同步后再替换，失败时保留原来的完整缓存。"""
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{INDEX_PATH.name}.", suffix=".tmp",
                                    dir=INDEX_PATH.parent)
        temporary_path = Path(name)
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, INDEX_PATH)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _validate(self) -> None:
        import sklearn
        from scipy.sparse import issparse
        from sklearn.exceptions import NotFittedError
        from sklearn.feature_extraction.text import TfidfVectorizer

        metadata = getattr(self, "metadata", None)
        if not isinstance(metadata, dict) or metadata.get("format_version") != _INDEX_FORMAT_VERSION:
            raise _InvalidIndex("索引格式过旧或缺少格式元数据")
        if metadata.get("sklearn_version") != sklearn.__version__:
            raise _InvalidIndex("索引与当前 scikit-learn 版本不一致")
        if not isinstance(getattr(self, "vectorizer", None), TfidfVectorizer):
            raise _InvalidIndex("缺少 TF-IDF 向量器")
        chunks = getattr(self, "chunks", None)
        if not isinstance(chunks, list) or not chunks or not all(isinstance(c, Chunk) for c in chunks):
            raise _InvalidIndex("知识块数据无效")
        matrix = getattr(self, "matrix", None)
        if not issparse(matrix) or matrix.ndim != 2 or matrix.shape[0] != len(chunks):
            raise _InvalidIndex("向量矩阵与知识块数量不一致")
        if matrix.shape[1] == 0 or not np.isfinite(matrix.data).all():
            raise _InvalidIndex("向量矩阵包含无效数据")
        # pickle 能加载不代表模型可用；跨版本残缺状态常在 transform 才报错。
        try:
            probe = self.vectorizer.transform(["index validation"])
            if probe.shape != (1, matrix.shape[1]) or not np.isfinite(probe.data).all():
                raise _InvalidIndex("向量器与索引列数不一致或输出无效")
            scores = (matrix @ probe.T).toarray()
            if scores.shape != (len(chunks), 1) or not np.isfinite(scores).all():
                raise _InvalidIndex("索引检索探针失败")
        except (AttributeError, NotFittedError, ValueError) as exc:
            raise _InvalidIndex(f"索引无法执行检索：{exc}") from exc

    @classmethod
    def load(cls) -> "RagIndex":
        from sklearn.exceptions import InconsistentVersionWarning

        try:
            cache_file = open(INDEX_PATH, "rb")
        except FileNotFoundError:
            _LOG.info("RAG 索引不存在，首次构建")
        else:
            try:
                with cache_file, warnings.catch_warnings():
                    warnings.simplefilter("error", InconsistentVersionWarning)
                    idx = pickle.load(cache_file)
            except (AttributeError, ModuleNotFoundError, pickle.UnpicklingError,
                    EOFError, ValueError, InconsistentVersionWarning) as exc:
                # 此处仅包围反序列化，不捕获数据库/系统/任意模型运行异常。
                _LOG.warning("RAG 索引缓存无法加载，将从语料重建：%s", exc)
            else:
                try:
                    if not isinstance(idx, cls):
                        raise _InvalidIndex("缓存类型不是 RagIndex")
                    idx._validate()
                except _InvalidIndex as exc:
                    _LOG.warning("RAG 索引缓存校验失败，将从语料重建：%s", exc)
                else:
                    return idx
        idx = cls()
        idx.build()
        return idx

    def search(self, query: str, k: int = _TOP_K) -> list[tuple[Chunk, float]]:
        vec = self.vectorizer.transform([query])
        scores = (self.matrix @ vec.T).toarray().ravel()
        top = np.argsort(scores)[::-1][:k]
        return [(self.chunks[i], float(scores[i])) for i in top if scores[i] >= _MIN_SCORE]


def search(query: str, k: int = _TOP_K) -> list[tuple[Chunk, float]]:
    return RagIndex.load().search(query, k)


# ---------------- CLI：重建索引 ----------------

if __name__ == "__main__":
    import sys

    # 关键：通过 agent.rag 模块路径调用，保证 pickle 记录的类路径是
    # agent.rag.RagIndex 而非 __main__.RagIndex（否则其他进程无法加载索引）
    from agent import rag as _rag

    if "--rebuild" in sys.argv:
        n = _rag.RagIndex().build()
        print(f"索引已重建：{n} 个知识块 -> {_rag.INDEX_PATH}")
    else:
        q = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "Houthi attack on merchant vessel"
        for chunk, score in _rag.search(q):
            print(f"[{score:.3f}] {chunk.title}\n  {chunk.text[:150]}...\n")
