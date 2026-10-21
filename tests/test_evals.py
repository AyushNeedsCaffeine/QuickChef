from types import SimpleNamespace

from evals import run_evals as ev


def _run(ingredients, steps):
    return SimpleNamespace(outputs={"ingredients": ingredients, "steps": steps})


def _example(must_include, must_exclude, min_steps=3):
    return SimpleNamespace(
        outputs={"must_include": must_include, "must_exclude": must_exclude, "min_steps": min_steps}
    )


def test_includes_passes_when_present():
    run = _run(["Rajma (Kidney beans)", "Tomato"], ["a", "b", "c"])
    ex = _example([["rajma", "kidney"]], [])
    assert ev.includes(run, ex)["score"] == 1.0


def test_includes_fails_when_missing():
    run = _run(["Tomato"], ["a", "b", "c"])
    ex = _example([["mushroom"]], [])
    assert ev.includes(run, ex)["score"] == 0.0


def test_excludes_fails_when_forbidden_present():
    run = _run(["Onion", "Garlic", "Rajma"], ["a", "b", "c"])
    ex = _example([], [["onion"], ["garlic"]])
    assert ev.excludes(run, ex)["score"] == 0.0


def test_excludes_passes_when_clean():
    run = _run(["Rajma", "Tomato", "Ginger"], ["a", "b", "c"])
    ex = _example([], [["onion"], ["garlic"]])
    assert ev.excludes(run, ex)["score"] == 1.0


def test_steps_threshold():
    assert ev.steps_ok(_run([], ["a", "b"]), _example([], [], min_steps=3))["score"] == 0.0
    assert ev.steps_ok(_run([], ["a", "b", "c"]), _example([], [], min_steps=3))["score"] == 1.0
