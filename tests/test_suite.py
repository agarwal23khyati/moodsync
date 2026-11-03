"""pytest entry point: python -m pytest tests -q   (uses the in-memory DB; no MongoDB needed)"""
import os, sys
os.environ["MOODSYNC_MOCK"] = "1"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))
import pytest
import suite as S


@pytest.fixture(scope="module")
def stack():
    S.start_servers(8100, 8101)
    return "http://127.0.0.1:8100"


def test_normalisation():
    r = S.exp_normalisation(); assert r["passed"] == r["total"]

def test_styling_reranking():
    r = S.exp_styling_reranking(); assert r["passed"] == r["total"] == 24

def test_worn_penalty_rotates_outfits():
    r = S.exp_worn_penalty(seed_base=5000); assert r["passed"] / r["total"] >= 0.9, r["failed_trials"]

def test_referential_integrity(stack):
    r = S.exp_referential_integrity(); assert r["orphans_after_deletes"] == 0 and r["negative_control_detects_planted_orphan"]

def test_task_analytics_matches_oracle():
    r = S.exp_task_analytics(); assert r["passed"] == r["total"]

def test_music_and_recipe_agents(stack):
    r = S.exp_music_recipe(S.Api(stack).signup("pt"))
    assert r["music"]["passed"] == r["music"]["total"] and r["recipe"]["passed"] == r["recipe"]["total"]

def test_inter_service_payloads(stack):
    r = S.exp_integration(stack, n=60); assert r["schema_mismatches"] == 0 and r["completed_clean"] == 60

def test_latency_target(stack):
    r = S.exp_latency(stack, n=20); assert r["within_target"]

def test_coordinator_survives_agent_outage(stack):
    """If one agent fails the Coordinator still returns the others (graceful degradation)."""
    import agent_service
    api = S.Api(stack).signup("deg")
    orig = agent_service.music
    # break the music route by swapping the route handler's endpoint
    for route in agent_service.app.routes:
        if getattr(route, "path", "") == "/agents/music":
            real = route.endpoint
            def boom(*a, **k): raise RuntimeError("down")
            route.endpoint = boom; route.dependant.call = boom
            try:
                j = api.post("/context", json={"mood": "calm", "occasion": "Casual"}).json()
            finally:
                route.endpoint = real; route.dependant.call = real
            assert "music" in j["errors"] and "styling" in j["suggestions"] and "recipe" in j["suggestions"]
            return
    pytest.skip("route not found")
