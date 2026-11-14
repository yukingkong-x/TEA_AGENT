"""知识库（REQ-F-020）：上传 → 切片 → 向量化 → 入库 → 检索。

对外只有两个接缝（见 app/seams.py）：
    loader.ingest(path, doc_id) -> {"chunk_count": int, "chroma_ids": [...]}
    retriever.search(question, top_k) -> [{"title", "chunk_text", "score", "doc_id"}]

设计取舍（为什么不用 Chroma 自带的 embedding）：
    1) chromadb 官方 embedding 默认拉 all-MiniLM 模型，演示机上首次运行要联网下载，
       彩排现场不可接受；
    2) 我们的文本以中文农艺条文为主，字符 n-gram 哈希向量在小语料上召回够用，
       且完全确定性——同样输入永远同样向量，便于回归测试；
    3) 向量由本进程算好再交给 Chroma 存，检索/入库两侧空间一致，不会出现
       「入库用 A 模型、查询用 B 模型」的静默错配。

Chroma 只是索引镜像，本地 JSON 才是兜底：容器没起时 RAG 不能哑火。
"""
