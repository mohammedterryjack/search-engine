# Models Used in SearChi

This document lists all the machine learning models used across SearChi's services.

## Document Parsing (Parser Service)

**Service**: `parser` (3 replicas)  
**Purpose**: Extract text, tables, figures, and structure from documents

### Docling
- **Model**: Multiple models from [DS4SD/Docling](https://github.com/DS4SD/docling)
  - Layout detection: `docling-layout-heron` (~172MB)
  - Document understanding: `SmolDocling-256M-preview` (770 weights)
- **Backend**: ONNX Runtime (optimized for CPU inference)
- **Memory**: ~2.6GB peak per document
- **Supported formats**: PDF, DOCX, PPTX, XLSX, HTML, MD, images

### RapidOCR
- **Models**: PP-OCRv4 (ONNX format)
  - Text detection: `ch_PP-OCRv4_det_infer.onnx` (~14MB)
  - Text classification: `ch_ppocr_mobile_v2.0_cls_infer.onnx` (~0.6MB)
  - Text recognition: `ch_PP-OCRv4_rec_infer.onnx` (~26MB)
- **Backend**: ONNX Runtime
- **Purpose**: OCR for scanned documents and images

## Text Summarization (Summariser Service)

**Service**: `summariser`  
**Model**: [Falconsai/text_summarization](https://huggingface.co/Falconsai/text_summarization)  
**Architecture**: T5-small (Seq2Seq)  
**Size**: ~244MB  
**Purpose**: Generate concise summaries of search results  
**Max input**: 512 tokens  
**Output**: 10-50 tokens (configurable)

## Result Reranking (Reranker Service)

**Service**: `reranker`  
**Model**: [cross-encoder/ms-marco-MiniLM-L4-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L4-v2)  
**Architecture**: MiniLM-L4 (Cross-encoder)  
**Size**: ~50MB  
**Purpose**: Rerank search results by query relevance  
**Batch size**: 16

## Vector Search (Web Service)

**Service**: `web`  
**Model**: [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)  
**Architecture**: MiniLM-L6 (Bi-encoder)  
**Size**: ~90MB  
**Purpose**: Generate embeddings for semantic search  
**Vector dimensions**: 384  
**Backend**: FAISS (CPU)

## Model Caching

All Hugging Face models are cached at:
```
~/.searchi/model_cache/huggingface/
```

This prevents re-downloading models and saves container disk space.

## Memory Requirements

| Service | Memory Limit | Memory Reservation |
|---------|-------------|-------------------|
| Parser  | 4GB         | 1GB               |
| Summariser | Default  | Default           |
| Reranker | Default   | Default           |
| Web     | Default     | Default           |

## Performance Notes

- **Parser**: Uses ONNX Runtime instead of PyTorch for 3-5x better memory efficiency
- **Vector Search**: FAISS indexing is CPU-only but fast for <100k documents
- **Summariser**: T5-small is 12x smaller than previous qwen2.5 model
- **Reranker**: Cross-encoder provides better relevance than bi-encoder alone

## Model Updates

To update models, modify the respective service configuration:

```yaml
# docker-compose.yml
parser:
  labels:
    - "searchi.model=docling"  # Update here

summariser:
  labels:
    - "searchi.model=Falconsai/text_summarization"  # Update here

reranker:
  environment:
    SEARCHY_RERANKER_MODEL: cross-encoder/ms-marco-MiniLM-L4-v2  # Update here
```

Then rebuild: `docker compose up --build -d`
