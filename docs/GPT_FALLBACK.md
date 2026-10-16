# Gemini → GPT fallback

## Configuration

Set `OPENAI_API_KEY` in the server `.env` (comma-separated keys supported),
`GPT_FALLBACK=true`, `OPENAI_BASE_URL=https://api.openai.com/v1`,
`OPENAI_LLM_MODEL=gpt-4o-mini` and `OPENAI_EMBED_MODEL=text-embedding-3-small`.
Keys stay on the backend and must never be included in frontend assets.
After changing environment variables, recreate the app container so it receives them.

## LLM requests

Understanding, reranking, enrichment and evaluation generation use Gemini first.
Transient errors/quota exhaustion can use GPT within the original request deadline.
Malformed inputs are not retried through another provider. GPT receives the output
schema in its instructions; its JSON is validated before the pipeline can use it.
Queueing, limiter waits, retries and backoff count toward the GPT request timeout.

## Embeddings: prepare, then activate

Equal dimensions do not make Gemini and OpenAI vectors compatible. A query must
use the model that generated the catalog's active vectors.

When an offline Gemini embedding job exhausts quota, it prepares GPT vectors with
`embed_demo(target_model=...)`. Checkpoints for both models coexist in storage;
the table's active model remains unchanged while preparing. Once the entire GPT
snapshot succeeds, the job atomically updates the active model with an expected
catalog version and reloads the index. A catalog change forces a bounded re-plan.

If GPT fails, the old model and old vectors remain usable. No vectors are deleted.
Later retries reuse completed GPT checkpoints. Online query embedding never silently
switches provider against an incompatible catalog; the existing lexical fallback
remains available if the active embedding provider fails.

## Error handling

- 429 rate limiting: honour cooldown/Retry-After and rotate available keys.
- `insufficient_quota` / `credit_balance_exhausted`: billing quota, not transient
  rate limiting; suspend the affected key for one hour without repeated calls.
- 401/403: suspend the invalid/unauthorized key and try another configured key.
- 5xx/network errors: bounded retries; output/body contents are not echoed in errors.
- Validate embedding count, unique ordered indices, dimensions, finite/nonzero
  values and response model. Reject malformed/refused/truncated LLM output.
- Full health exposes configured/available key counts and cooldown reasons, never keys.

After adding credit, restart/recreate the app to clear an in-memory billing
cooldown immediately, or wait for it to expire. Do not rerun full catalog jobs
while all configured providers remain out of credit/quota.

## Verification on 16/10/2026

EC2 already contained a configured GPT key and enabled fallback. Two small
synthetic requests (chat + embedding) returned 429 `credit_balance_exhausted`.
This is an external billing block; successful live GPT inference cannot be claimed.
Unit/integration tests use fake providers/HTTP transports to verify the fallback,
schema validation, deadlines, staging failure and atomic activation independently.

The King Coffee table had selected GPT with zero GPT vectors. Its 387 existing
Gemini vectors matched current source hashes; the active model was restored to
Gemini without deleting rows/vectors. It has 753 rows and needs 1,506 vectors in
total: this recovery restores partial coverage, not a completed embedding job.

Official references: [Embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create),
[Chat completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
