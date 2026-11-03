"""Run every experiment and write results/ (results.json, results.md, figures).

  python experiments/run_experiments.py --mock     # self-contained: in-memory DB, both services started for you
  python experiments/run_experiments.py            # against YOUR running stack (START.bat) + real MongoDB  <- use for the paper
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import suite as S

ap = argparse.ArgumentParser()
ap.add_argument("--mock", action="store_true", help="in-memory mongomock DB, start both services in-process")
ap.add_argument("--base", default="http://127.0.0.1:8000", help="Coordinator URL when not --mock")
ap.add_argument("--users", type=int, default=200, help="simulated users")
a = ap.parse_args()
OUT = S.ROOT / "results"; OUT.mkdir(exist_ok=True)

if a.mock: S.start_servers()
else:
    import os; os.environ.pop("MOODSYNC_MOCK", None)
base = a.base
R = {"environment": S.environment(a.mock)}
step = lambda name, fn, *args: (print(f"... {name}", flush=True), R.__setitem__(name, fn(*args)), print(f"    done", flush=True))
step("normalisation", S.exp_normalisation)
step("styling_reranking", S.exp_styling_reranking)
step("worn_penalty", S.exp_worn_penalty)
step("referential_integrity", S.exp_referential_integrity)
step("task_analytics", S.exp_task_analytics)
step("music_recipe", S.exp_music_recipe, S.Api(base).signup("mr"))
step("integration", S.exp_integration, base)
step("latency", S.exp_latency, base)
step("simulation", S.exp_simulation, a.users)
R["environment"]["note"] = ("Latency: Coordinator, agent service and DB on ONE machine; network delay excluded. "
                            + ("MOCK RUN: in-memory database, numbers are NOT for the paper." if a.mock else "Real MongoDB run."))
(OUT / "results.json").write_text(json.dumps(R, indent=1))

# ------------------------------------------------------------------ figures
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
mr = R["music_recipe"]
rows = [("Outfit re-ranking\n(%d/%d)" % (R["styling_reranking"]["passed"], R["styling_reranking"]["total"]), R["styling_reranking"]["passed"] / R["styling_reranking"]["total"]),
        ("Worn-count penalty\n(%d/%d)" % (R["worn_penalty"]["passed"], R["worn_penalty"]["total"]), R["worn_penalty"]["passed"] / R["worn_penalty"]["total"]),
        ("Referential integrity\n(%d outfits)" % R["referential_integrity"]["outfits_seeded"], R["referential_integrity"]["passed"]),
        ("Task analytics vs oracle\n(%d/%d)" % (R["task_analytics"]["passed"], R["task_analytics"]["total"]), R["task_analytics"]["passed"] / R["task_analytics"]["total"]),
        ("Music agent\n(%d/%d)" % (mr["music"]["passed"], mr["music"]["total"]), mr["music"]["passed"] / mr["music"]["total"]),
        ("Recipe agent\n(%d/%d)" % (mr["recipe"]["passed"], mr["recipe"]["total"]), mr["recipe"]["passed"] / mr["recipe"]["total"]),
        ("Inter-service payload\n(%d/%d)" % (R["integration"]["completed_clean"], R["integration"]["total"]), R["integration"]["completed_clean"] / R["integration"]["total"])]
fig, ax = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [2.2, 1]})
ax[0].barh([r[0] for r in rows][::-1], [100 * r[1] for r in rows][::-1], color="#4c72b0", edgecolor="k")
for i, v in enumerate([100 * r[1] for r in rows][::-1]): ax[0].text(min(v + 1, 88), i, f"{v:.0f}%", va="center", fontweight="bold")
ax[0].set_xlim(0, 105); ax[0].set_xlabel("Success rate (%)"); ax[0].set_title("(a) Functional and integration outcomes", fontweight="bold")
L = R["latency"]
ax[1].bar(["Measured\n(mean of %d runs)" % L["runs"], "Permissible\nlimit"], [L["mean_ms"], L["target_ms"]], color=["#4c72b0", "#dddddd"], edgecolor="k")
ax[1].text(0, L["mean_ms"] + 8, f'{L["mean_ms"]:.0f} ms', ha="center", fontweight="bold"); ax[1].text(1, L["target_ms"] + 8, "500 ms", ha="center", fontweight="bold")
ax[1].set_ylabel("Round-trip latency (ms)"); ax[1].set_ylim(0, max(600, L["max_ms"] * 1.1)); ax[1].set_title("(b) Outfit-request latency", fontweight="bold")
plt.tight_layout(); plt.savefig(OUT / "fig5_results.png", dpi=200); plt.close()

sim = R["simulation"]["by_rho"]
fig, axs = plt.subplots(1, len(sim), figsize=(4.2 * len(sim), 3.6), sharey=True)
cols = {"siloed": "#c44e52", "shared": "#4c72b0", "shared+learning": "#55a868"}
for ax_, (rho, d) in zip(axs if len(sim) > 1 else [axs], sim.items()):
    for m, c in d["curves"].items(): ax_.plot(range(1, len(c) + 1), c, label=m, color=cols[m], lw=1.8)
    ax_.set_title(f"individual variation rho = {rho}"); ax_.set_xlabel("round"); ax_.grid(alpha=.3)
axs[0].set_ylabel("mean acceptance rate"); axs[0].legend(fontsize=8)
plt.tight_layout(); plt.savefig(OUT / "fig6_simulation.png", dpi=200); plt.close()

# ------------------------------------------------------------------ markdown tables for the paper
pct = lambda p, t: f"{100 * p / t:.0f}% ({p}/{t})"
E_ = R["environment"]
md = [f"# MoodSync results ({'MOCK RUN - do not publish' if a.mock else 'real run'})", "",
      "## Test environment (fills Section IV-A placeholders)", "",
      f"CPU: {E_['cpu']} | RAM: {E_['ram_gb']} GB | OS: {E_['os']} | Python {E_['python']} | FastAPI {E_['fastapi']} | Uvicorn {E_['uvicorn']} | "
      f"PyMongo {E_['pymongo']} | Pydantic {E_['pydantic']} | pandas {E_['pandas']} | test framework: pytest {E_['pytest']} | DB: {E_['database']}", "",
      "## Table II - functional and integration results", "", "| Metric | Result |", "|---|---|",
      f"| Outfit re-ranking, mood/occasion change | {pct(R['styling_reranking']['passed'], R['styling_reranking']['total'])} |",
      f"| Worn-count penalty (no repeat in 3 cycles) | {pct(R['worn_penalty']['passed'], R['worn_penalty']['total'])} |",
      f"| Referential integrity (outfits -> items/mood logs, {R['referential_integrity']['outfits_seeded']} outfits, {R['referential_integrity']['items_deleted']} items deleted) | {R['referential_integrity']['orphans_after_deletes']} orphans |",
      f"| Task analytics vs independent oracle | {pct(R['task_analytics']['passed'], R['task_analytics']['total'])} |",
      f"| Music agent checks | {pct(mr['music']['passed'], mr['music']['total'])} |",
      f"| Recipe agent checks | {pct(mr['recipe']['passed'], mr['recipe']['total'])} |",
      f"| Inter-service payload (Coordinator -> agents), clean responses | {pct(R['integration']['completed_clean'], R['integration']['total'])}; schema mismatches: {R['integration']['schema_mismatches']} |",
      f"| Mean round-trip latency ({L['runs']} runs, after {L['warmup_discarded']} warm-up) | {L['mean_ms']} ms (median {L['median_ms']}, p95 {L['p95_ms']}, max {L['max_ms']}) |",
      "| Usability: wizard completed unaided | FILL FROM YOUR REAL USER STUDY (see docs/USABILITY_PROTOCOL.md) |", "",
      "## Simulation: shared mood context vs siloed modules", "",
      f"{R['simulation']['n_users']} simulated users x {R['simulation']['rounds']} rounds. rho = how much a user's hidden taste deviates from the population rules.", "",
      "| rho | siloed | shared context | shared + feedback | shared - siloed (paired, 95% CI) | learning gain (paired, 95% CI) |", "|---|---|---|---|---|---|"]
for rho, d in sim.items():
    f = lambda m: f"{d['acceptance'][m]['mean']:.3f} +/- {d['acceptance'][m]['ci95']:.3f}"
    md.append(f"| {rho} | {f('siloed')} | {f('shared')} | {f('shared+learning')} | {d['shared_minus_siloed']['mean']:+.3f} +/- {d['shared_minus_siloed']['ci95']:.3f} | {d['learning_minus_shared']['mean']:+.3f} +/- {d['learning_minus_shared']['ci95']:.3f} |")
md += ["", "Mood entries per session: siloed = 4 (one per module), shared = 1 (by design, not measured).", "",
       "Details: styling-case failures: " + str([d for d in R['styling_reranking']['details'] if not d['pass']]),
       f"; worn-penalty failed trials: {R['worn_penalty']['failed_trials']}; recipe/music failures: {mr['music']['failed']} {mr['recipe']['failed']}"]
(OUT / "results.md").write_text("\n".join(md))

# ------------------------------------------------------------------ ready-to-paste prose, filled from the measured numbers
sr, wp, ri, ta, ig = R["styling_reranking"], R["worn_penalty"], R["referential_integrity"], R["task_analytics"], R["integration"]
d5, d75 = sim["0.5"], sim[sorted(sim, key=float)[-1]]
def sig(d):   # honest wording from the confidence interval
    m, c = d["mean"], d["ci95"]
    return ("improved acceptance by %.1f percentage points (95%% CI +/-%.1f)" % (100 * m, 100 * c)) if m - c > 0 else \
           ("showed no statistically reliable change (%+.1f pp, 95%% CI +/-%.1f)" % (100 * m, 100 * c))
txt = f"""# Paper text generated from the measured results ({'MOCK RUN - DO NOT PUBLISH THESE NUMBERS' if a.mock else 'real run'})

## IV-A Test Environment
All tests ran on a single local machine ({E_['cpu']}, {E_['ram_gb']} GB RAM, {E_['os']}) running Python {E_['python']} with FastAPI {E_['fastapi']}, Uvicorn {E_['uvicorn']}, PyMongo {E_['pymongo']}, pandas {E_['pandas']} and {E_['database']}; the frontend was plain HTML/JavaScript. Unit tests used pytest {E_['pytest']}. Latency was measured over {L['runs']} sequential outfit-suggestion requests (after {L['warmup_discarded']} discarded warm-up requests) with the Coordinator, agent service and database on the same machine, so network delay is excluded. Referential-integrity tests used {ri['outfits_seeded']} seeded outfit records.

## IV-B Module-Level Testing
Unit tests of the Styling Agent's scoring showed that the top-ranked outfit satisfied the hand-written occasion and mood rules in {sr['passed']} of {sr['total']} mood-occasion combinations (4 moods x 6 occasions) on a factorial test wardrobe; changing the mood alone changed the top outfit in {sr['mood_pairs_that_change_top_outfit']} mood pairs. The worn-count penalty rotated outfits correctly (no outfit repeated within {3} wears) in {wp['passed']} of {wp['total']} held-out trials ({100*wp['passed']/wp['total']:.0f}%); the penalty weight ({wp['worn_weight']}) was chosen on separate development seeds, and the rotation reduces the average fit of the chosen outfit to {100*wp['mean_fit_retained']:.0f}% of the no-penalty optimum, so variety is bought at a cost in fit. The Task Agent's analytics (completion rate, streak, week-over-week change, per-mood rates) matched an independent reference implementation in {ta['passed']} of {ta['total']} randomised cases. The Music Agent passed {mr['music']['passed']} of {mr['music']['total']} checks (category match, single upserted feedback document, skipped tracks demoted) and the Recipe Agent {mr['recipe']['passed']} of {mr['recipe']['total']} (overlap matches an independent oracle, ranking monotone in overlap, a rejection demotes a recipe). Referential-integrity tests found {ri['orphans_after_deletes']} orphaned outfit references after {ri['items_deleted']} wardrobe items were deleted ({ri['outfits_removed_by_cascade']} dependent outfits were removed by the application-level cascade); a planted orphan was detected by the checker.

## IV-C Integration Testing
Requests were sent to the Coordinator REST API, which dispatched them concurrently to the four agents over HTTP and re-validated every response against shared Pydantic contracts. {ig['completed_clean']} of {ig['total']} requests (including synonym moods, unicode occasions and a user with no data) completed with {ig['schema_mismatches']} schema mismatches. The mean round-trip latency was {L['mean_ms']} ms (median {L['median_ms']} ms, 95th percentile {L['p95_ms']} ms) over {L['runs']} runs, {'below' if L['within_target'] else 'ABOVE'} the 500 ms target adopted for interactive use.

## IV-D Usability Testing
[FILL FROM YOUR REAL STUDY: n, how many finished the wizard unaided, how many understood that the mood now also re-ranks recipes. See docs/USABILITY_PROTOCOL.md. Do not reuse the old 5/5 and 3/5 figures unless that study was run on this version.]

## IV-E Simulation Study: Shared Mood Context versus Siloed Modules
To estimate the effect of sharing the mood context, {R['simulation']['n_users']} simulated users with hidden, mood-dependent tastes interacted with the system for {R['simulation']['rounds']} rounds, accepting or rejecting the top outfit, track and recipe with a probability derived from their taste. Three conditions used identical users and random draws: siloed modules that ignore mood, the shared mood context, and the shared context with accept/reject adaptation. The parameter rho sets how far a user's taste departs from the population rules. At rho = 0.5 the shared mood context raised mean acceptance from {d5['acceptance']['siloed']['mean']:.3f} to {d5['acceptance']['shared']['mean']:.3f} (paired difference {100*d5['shared_minus_siloed']['mean']:+.1f} pp, 95% CI +/-{100*d5['shared_minus_siloed']['ci95']:.1f}); at rho = {sorted(sim, key=float)[-1]} the difference was {100*d75['shared_minus_siloed']['mean']:+.1f} pp (+/-{100*d75['shared_minus_siloed']['ci95']:.1f}). Accept/reject adaptation {sig(d5['learning_minus_shared'])} at rho = 0.5. Siloed modules also require the mood to be entered four times per session instead of once, which is a design property rather than a measured quantity. This is a simulation: the users are generated from the same mood vocabulary as the agents, so part of the shared-context advantage is built in by construction{' (it shrinks as rho grows)' if d5['shared_minus_siloed']['mean'] > d75['shared_minus_siloed']['mean'] else ''}; it is evidence about the mechanism, not about real users.

## IV-F Limitations (replace the old list)
(i) The usability study is small and was run with students. (ii) Agents are rule-based with static tables; the only adaptation is the accept/reject preference memory, and in simulation it {sig(d5['learning_minus_shared']).split(' (')[0]}. (iii) Quantitative testing of the Music and Recipe agents checks correctness of the rules, not recommendation quality for real users. (iv) The simulation study uses synthetic users and shares its vocabulary with the agents. (v) Latency excludes network delay and was measured on one machine. (vi) The sensitivity of results to the hand-set weights was not studied.
"""
(OUT / "paper_text.md").write_text(txt)

print("\n".join(md)); print("\nWrote", OUT)
