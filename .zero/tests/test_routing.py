"""
Offline routing checks — no network, no LLM, runs in a second.

    cd K:\\Zero\\.zero && K:\\Zero\\.venv\\Scripts\\python.exe tests\\test_routing.py

Every case here is a real message that was once routed wrong:
- cricket scores edited the snake game (follow-up rule too loose)
- "Asian Games, give me the result" built a website ("give me" + "games")
- "improve this email" re-opened snake.html ("improve" + "this")
- "Ukraine" was classed as AI news ("ukr-AI-ne")
- Herald never searched a specific question
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.news.run import _detect_news_type, _specific_question
from core.intent import is_build_followup, is_game_build, is_game_fix

BUILT = "[USER]: make me a snake game\n[ZERO]: Done - I built it and saved it to K:\\Zero\\Zero Tech\\snake.html."
OTHER = "[USER]: what's the weather\n[ZERO]: Overcast in Manchester, rain likely."


def test_followups() -> None:
    for q in ["make it faster and harder",
              "Create levels with three lives each. End the game at 30 points.",
              "add a scoreboard", "the game won't start", "make the snake move quicker"]:
        assert is_build_followup(BUILT, q), q
    for q in ["Today's India Pakistan match results", "what's the weather in Manchester",
              "give me a briefing", "latest research on motor imagery BCI",
              "find my dissertation notes", "draft an email to my supervisor", "explain CSP for EEG",
              "make me a snake game", "build me a new racing game", "redo it from scratch"]:
        assert not is_build_followup(BUILT, q), q
    for q in ["make it faster and harder", "add a scoreboard"]:     # previous turn wasn't a build
        assert not is_build_followup(OTHER, q), q
    assert not is_build_followup("", "make it faster")


def test_game_builds_only() -> None:
    for q in ["make me a snake game", "build a tetris game", "create a simple 2d platformer game",
              "make an arcade shooter", "code me a pong game"]:
        assert is_game_build(q), q
    for q in ["The india and Pakistan match in Asian games give me the result",
              "Today's India Pakistan match results.", "build me a website for my portfolio",
              "make me a landing page", "create a dashboard of my spending",
              "make a game plan for my exams", "who won the olympic games 100m",
              "write a python function to compute PSD"]:
        assert not is_game_build(q), q


def test_game_fixes() -> None:
    for q in ["the game won't start", "fix the snake game", "make the game harder"]:
        assert is_game_fix(q), q
    for q in ["improve this email", "fix it", "fix the website", "change my meeting to 3pm",
              "the asian games schedule changed"]:
        assert not is_game_fix(q), q


def test_news() -> None:
    assert _detect_news_type("what's going on in Ukraine") == "world"
    assert _detect_news_type("rain in Bahrain and Dubai") == "world"
    assert _detect_news_type("latest AI news") == "ai"
    assert _specific_question("Today's india and Pakistan result")
    assert _specific_question("who won the F1 race")
    assert not _specific_question("Give me the latest news")
    assert not _specific_question("what's the news today")


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("routing: all checks pass")
