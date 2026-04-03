from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

logger = logging.getLogger(__name__)

# Global model and tokenizer
_model = None
_tokenizer = None


def get_model():
    global _model, _tokenizer
    if _model is None:
        logger.info("Loading Falconsai/text_summarization model...")
        _tokenizer = AutoTokenizer.from_pretrained("Falconsai/text_summarization")
        _model = AutoModelForSeq2SeqLM.from_pretrained("Falconsai/text_summarization")
        logger.info("Model loaded successfully")
    return _model, _tokenizer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load model on startup
    get_model()
    yield


app = FastAPI(lifespan=lifespan)


class SummarizeRequest(BaseModel):
    text: str
    max_length: int = 60
    min_length: int = 10


@app.post("/summarize")
async def summarize(request: SummarizeRequest):
    model, tokenizer = get_model()

    # Truncate input if too long
    max_input_length = 512
    text = request.text[:max_input_length * 4]

    try:
        inputs = tokenizer(text, return_tensors="pt", max_length=512, truncation=True)
        summary_ids = model.generate(
            inputs["input_ids"],
            max_length=request.max_length,
            min_length=request.min_length,
            num_beams=4,
            early_stopping=True,
        )
        summary = tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        return {"summary": summary}
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return {"summary": "Summarization failed", "error": str(e)}


@app.get("/health")
async def health():
    return {"status": "healthy", "model": "Falconsai/text_summarization"}
