"""LangSmith evaluation for QuickChef recipe resolution.

Creates a LangSmith dataset of dish/servings cases (including ingredient
modifications) and scores the recipe resolver with rule-based evaluators.

Usage:
    python -m evals.run_evals

Requires GROQ_API_KEY (the resolver needs the LLM) and LANGSMITH_TRACING=true +
LANGSMITH_API_KEY in the environment/.env.
"""
from __future__ import annotations

import sys

from langsmith import Client, evaluate

from app import config
from app.agent.graph import resolve_recipe
from app.services import llm_quota

DATASET_NAME = "quickchef-recipes"

# Each group in must_include/must_exclude is "at least one of these tokens".
CASES = [
    {
        "dish": "Rajma without onion garlic",
        "servings": 4,
        "must_include": [["rajma", "kidney"]],
        "must_exclude": [["onion"], ["garlic"]],
        "min_steps": 3,
    },
    {
        "dish": "Mix veg with mushrooms",
        "servings": 4,
        "must_include": [["mushroom"]],
        "must_exclude": [],
        "min_steps": 3,
    },
    {
        "dish": "Paneer butter masala",
        "servings": 4,
        "must_include": [["paneer"]],
        "must_exclude": [],
        "min_steps": 3,
    },
    {
        "dish": "Chole",
        "servings": 6,
        "must_include": [["chickpea", "chana", "chole"]],
        "must_exclude": [],
        "min_steps": 3,
    },
    {
        "dish": "Dal makhani",
        "servings": 2,
        "must_include": [["dal", "urad", "lentil"]],
        "must_exclude": [],
        "min_steps": 3,
    },
]


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch.isspace()).strip()


def _names(ingredients) -> list[str]:
    return [_norm(str(name)) for name in ingredients]


def _group_present(names: list[str], group) -> bool:
    return any(any(tok in n for n in names) for tok in group)


def target(inputs: dict) -> dict:
    recipe = resolve_recipe(inputs["dish"], int(inputs["servings"]))
    if not recipe:
        return {"ingredients": [], "steps": [], "source": "none"}
    return {
        "ingredients": [i.name for i in recipe.ingredients],
        "steps": recipe.steps,
        "source": recipe.source,
    }


def includes(run, example) -> dict:
    names = _names((run.outputs or {}).get("ingredients", []))
    missing = [g for g in example.outputs.get("must_include", []) if not _group_present(names, g)]
    return {
        "key": "must_include",
        "score": 1.0 if not missing else 0.0,
        "comment": "ok" if not missing else f"missing {missing}",
    }


def excludes(run, example) -> dict:
    names = _names((run.outputs or {}).get("ingredients", []))
    found = [g for g in example.outputs.get("must_exclude", []) if _group_present(names, g)]
    return {
        "key": "must_exclude",
        "score": 0.0 if found else 1.0,
        "comment": f"found {found}" if found else "ok",
    }


def steps_ok(run, example) -> dict:
    n = len((run.outputs or {}).get("steps", []))
    need = example.outputs.get("min_steps", 3)
    return {
        "key": "min_steps",
        "score": 1.0 if n >= need else 0.0,
        "comment": f"{n} steps (need {need})",
    }


def ensure_dataset(client: Client) -> None:
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    dataset = client.create_dataset(
        DATASET_NAME,
        description="QuickChef recipe resolution incl. ingredient modifications",
    )
    client.create_examples(
        inputs=[{"dish": c["dish"], "servings": c["servings"]} for c in CASES],
        outputs=[
            {
                "must_include": c["must_include"],
                "must_exclude": c["must_exclude"],
                "min_steps": c["min_steps"],
            }
            for c in CASES
        ],
        dataset_id=dataset.id,
    )
    print(f"Created LangSmith dataset '{DATASET_NAME}' with {len(CASES)} examples.")


def main() -> None:
    if not config.LANGSMITH_ENABLED:
        print(
            "LangSmith is disabled. Set LANGSMITH_TRACING=true and a non-empty "
            "LANGSMITH_API_KEY in .env."
        )
        sys.exit(1)
    if not config.LLM_ENABLED:
        print("No Groq key set; the eval target needs the LLM. Set GROQ_API_KEY in .env.")
        sys.exit(1)

    llm_quota.LIMIT = 0
    client = Client()
    ensure_dataset(client)

    model_tag = config.GROQ_MODEL.split("/")[-1]
    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[includes, excludes, steps_ok],
        experiment_prefix=f"quickchef-{model_tag}",
        max_concurrency=2,
    )

    try:
        print(results.to_pandas().to_string())
    except Exception:
        _print_summary(client, results.experiment_name)


def _print_summary(client: Client, experiment_name: str) -> None:
    """Print per-case scores and evaluator averages without requiring pandas."""
    import statistics

    rows = []
    for run in client.list_runs(project_name=experiment_name, is_root=True, limit=100):
        scores = {f.key: f.score for f in client.list_feedback(run_ids=[run.id])}
        rows.append(((run.inputs or {}).get("dish", "?"), scores))

    print(f"\nExperiment: {experiment_name}")
    totals: dict[str, list] = {}
    for dish, scores in rows:
        print(f"  {dish:<34} {scores}")
        for key, value in scores.items():
            totals.setdefault(key, []).append(value)
    print("  averages:")
    for key, values in totals.items():
        print(f"    {key:<14} {statistics.mean(values):.2f}  ({sum(1 for v in values if v == 1)}/{len(values)})")


if __name__ == "__main__":
    main()
