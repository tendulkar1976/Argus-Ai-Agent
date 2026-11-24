"""Optional loopback-only evaluation provider. Requires llama-cpp-python and a GGUF model."""

import os
import secrets
import threading
from fastapi import FastAPI, Header, HTTPException
from llama_cpp import Llama
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from argus.contracts import Message

model_id = os.environ["ARGUS_LOCAL_MODEL_ID"]
api_key = os.environ["ARGUS_LOCAL_PROVIDER_KEY"]
runtime = Llama(
    model_path=os.environ["ARGUS_LOCAL_GGUF"],
    n_ctx=2048,
    n_threads=3,
    seed=19,
    verbose=False,
)
serial = threading.Lock()
app = FastAPI()


def auth(value):
    if not secrets.compare_digest(value or "", "Bearer " + api_key):
        raise HTTPException(401)


@app.get("/v1/models")
def models(authorization: str = Header(default="")):
    auth(authorization)
    return {
        "object": "list",
        "data": [{"id": model_id, "object": "model", "owned_by": "local"}],
    }


class Request(BaseModel):
    model: str
    messages: list[Message]
    max_tokens: int = Field(ge=1, le=256)
    temperature: float = 0
    stream: bool = False


@app.post("/v1/chat/completions")
async def chat(body: Request, authorization: str = Header(default="")):
    auth(authorization)
    if body.model != model_id or body.stream:
        raise HTTPException(
            422,
            "Local benchmark adapter supports nonstreaming requests to the loaded model",
        )

    def generate():
        with serial:
            return runtime.create_chat_completion(
                messages=[m.model_dump(exclude_none=True) for m in body.messages],
                model=model_id,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
                seed=19,
            )

    return await run_in_threadpool(generate)
