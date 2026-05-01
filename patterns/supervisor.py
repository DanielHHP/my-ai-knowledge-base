"""Supervisor Pattern: iterative Worker-Supervisor quality review loop.

Worker produces a JSON analysis report for a task.
Supervisor reviews the report on accuracy, depth, and format.
Reports that fail review are sent back to the Worker with feedback
for refinement, up to ``max_retries`` rounds.
"""

import json

from pipeline.model_client import quick_chat


def chat(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float | None = None,
) -> tuple[str, object]:
    resp = quick_chat(prompt, system_prompt=system_prompt, temperature=temperature)
    return resp.content, resp.usage


WORKER_TEMPERATURE = 0.7
SUPERVISOR_TEMPERATURE = 0.2


def _worker(task: str, feedback: str | None = None) -> str:
    """Worker Agent: generate a JSON analysis report for the given task.

    Args:
        task: The task description.
        feedback: Optional feedback from a previous failed review.

    Returns:
        The raw text of the generated report.
    """
    system_prompt = (
        "You are a diligent analyst. "
        "Given a task, produce a JSON analysis report with these fields:\n"
        "- title: str\n"
        "- summary: str (100-200 characters)\n"
        "- key_points: list[str]\n"
        "- conclusion: str\n\n"
        "Respond with valid JSON only. No markdown fences, no extra text."
    )
    prompt = f"Task: {task}"
    if feedback:
        prompt += f"\n\nPrevious review feedback (address these issues):\n{feedback}"
    text, _ = chat(prompt, system_prompt=system_prompt, temperature=WORKER_TEMPERATURE)
    return text


def _supervisor(report: str, task: str) -> dict:
    """Supervisor Agent: review a worker report on three quality dimensions.

    Args:
        report: The worker's generated report.
        task: The original task description.

    Returns:
        A dict with ``passed`` (bool), ``score`` (int, sum of dimensions),
        ``feedback`` (str), and ``dimensions`` (dict).
    """
    system_prompt = (
        "You are a strict quality reviewer. "
        "Evaluate the following analysis report on three dimensions:\n"
        "- accuracy (1-10): factual correctness and relevance\n"
        "- depth (1-10): thoroughness and insight\n"
        "- format (1-10): JSON validity and structure\n\n"
        "Output valid JSON only, using this schema:\n"
        '{"passed": bool, "score": int, "feedback": str, '
        '"dimensions": {"accuracy": int, "depth": int, "format": int}}\n\n'
        "The overall score is the sum of the three dimensions (max 30). "
        "A report passes when score >= 21 (average >= 7). "
        "No markdown fences, no extra text."
    )
    prompt = f"Task: {task}\n\nReport:\n{report}"
    text, _ = chat(prompt, system_prompt=system_prompt, temperature=SUPERVISOR_TEMPERATURE)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def supervisor(task: str, max_retries: int = 3) -> dict:
    """Run a Worker-Supervisor quality review loop.

    The Worker generates a JSON analysis report for the given task.
    The Supervisor reviews it on three dimensions (accuracy, depth, format).
    If the report passes (score >= 21 / 30) it is returned immediately.
    Otherwise the report is sent back to the Worker with the Supervisor's
    feedback for up to ``max_retries`` rounds. If no round passes, the
    last report is force-returned with a warning.

    Args:
        task: The task description for the Worker.
        max_retries: Maximum number of review-and-refine rounds (default 3).

    Returns:
        A dict with:
        - ``output``: The final worker report text.
        - ``attempts``: Number of attempts made.
        - ``final_score``: Score from the last review.
        - ``warning``: Present only when max retries exceeded.
    """
    feedback = None
    report = ""
    score = 0

    for attempt in range(1, max_retries + 1):
        report = _worker(task, feedback=feedback)
        review = _supervisor(report, task)
        score = review["score"]

        if review["passed"]:
            return {
                "output": report,
                "attempts": attempt,
                "final_score": score,
            }

        feedback = review["feedback"]

    return {
        "output": report,
        "attempts": max_retries,
        "final_score": score,
        "warning": (
            f"Max retries ({max_retries}) exceeded. "
            "Report may not meet quality standards."
        ),
    }


if __name__ == "__main__":
    result = supervisor(
        "Explain the concept of attention mechanism in transformers."
    )
    print(f"Attempts: {result['attempts']}")
    print(f"Final score: {result['final_score']}")
    if "warning" in result:
        print(f"WARNING: {result['warning']}")
    print(f"Output:\n{result['output']}")
