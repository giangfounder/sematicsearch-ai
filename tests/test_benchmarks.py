"""Cold benchmark requests must remain cold when they run concurrently."""
import asyncio

from app.config import Settings
from app.gemini.fake import FakeGemini
from app.search.pipeline import SearchService
from benchmarks.bench import search_bench
from tests.conftest import make_index


class _Catalog:
    def __init__(self, index):
        self.index = index
        self.on_swap = []

    def get(self, slug):
        return self.index if slug == "t" else None


def test_cold_benchmark_isolates_same_query_at_concurrency_two():
    async def run():
        settings = Settings(gemini_provider="fake", embed_dim=64, gemini_embed_model="fake-embed",
                            _env_file=None)
        gem = FakeGemini(settings)
        service = SearchService(settings, gem, _Catalog(make_index()))
        queries = ["máy giặt giá tốt"]

        cold = await search_bench(service, "t", queries, n=2, concurrency=2, mode="fast", cold=True)
        assert cold["latency_ms"]["total"]["n"] == 2
        assert cold["request_wall_ms"]["n"] == 2
        assert gem.calls["embed_query"] == 2
        assert service.emb_cache.stats()["size"] == 0

        warm = await search_bench(service, "t", queries, n=2, concurrency=2, mode="fast", cold=False)
        assert warm["latency_ms"]["total"]["n"] == 2
        assert gem.calls["embed_query"] == 3

    asyncio.run(run())
