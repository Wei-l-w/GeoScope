"""RAG 空间知识库（M3）：新闻正文 + ACLED 事件描述 -> 可检索知识块。

架构说明（面试可讲）：
- 检索接口为标准「embed -> 向量 -> 余弦相似 top-k」，与稠密向量方案完全同构；
- 当前嵌入端点为 TF-IDF 稀疏向量（scikit-learn），原因：所用 LLM 代理无
  /embeddings 端点。换稠密模型时只需替换 _TfidfBackend，检索/存储/工具层不动；
- 跨语言问题用「LLM 查询改写」解决：语料为英文，Agent 被引导用英文关键词检索。

重建索引：
    python -m agent.rag --rebuild
"""

from __future__ import annotations

import pickle
import re
from dataclasses import dataclass

import numpy as np

from . import config, db

INDEX_PATH = config.ROOT / "data" / "rag_index.pkl"
_CHUNK_SIZE = 600   # 字符数，新闻正文切块
_CHUNK_OVERLAP = 100
_TOP_K = 5
_MIN_SCORE = 0.05   # 低于此相似度视为不相关，防幻觉引用


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

    def build(self) -> int:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.chunks = load_corpus()
        if not self.chunks:
            raise RuntimeError("语料为空：请先入库 news / acled 数据")
        self.vectorizer = TfidfVectorizer(max_features=30000, ngram_range=(1, 2),
                                          stop_words="english")
        self.matrix = self.vectorizer.fit_transform(c.text for c in self.chunks)
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(INDEX_PATH, "wb") as f:
            pickle.dump(self, f)
        return len(self.chunks)

    @classmethod
    def load(cls) -> "RagIndex":
        if not INDEX_PATH.exists():
            idx = cls()
            n = idx.build()
            print(f"[RAG] 首次构建索引：{n} 个知识块")
            return idx
        try:
            with open(INDEX_PATH, "rb") as f:
                return pickle.load(f)
        except (AttributeError, ModuleNotFoundError, pickle.UnpicklingError):
            # 索引文件损坏或由 __main__ 上下文构建（类路径失真）时自动重建
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
