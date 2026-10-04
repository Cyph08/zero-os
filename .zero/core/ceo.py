"""
core/ceo.py — Zero OS CEO Agent

The central orchestrator. Receives a user command, classifies intent,
selects the best agent(s), dispatches tasks, and synthesises the final response.

Cost routing:
    read/simple  → claude-haiku or local-7b
    multi-step   → claude-sonnet
    planning     → claude-sonnet
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import re

from core.bus import ContextBus
from core.errlog import log_error
from core.intent import (IntentClassifier, IntentResult, RiskLevel, classifier,
                         is_build_followup, is_game_build, is_game_fix)
from core.llm import chat, detect_provider
from core.personas import persona_state, PERSONAS
from core.quality import grade_and_fix, assess_depth, iters_for
from core.registry import AgentRegistry, AgentManifest, registry
from memory.hot import hot_memory
from memory.warm import warm_memory
from memory.cold import cold_memory

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).parent.parent / "logs"
ZERO_ROOT = Path(__file__).parent.parent

# Cosine distance (0 = identical, 1 = unrelated) a note or a rated answer must
# beat to be put in front of the model. Lower = stricter = fewer excerpts sent
# to the cloud. Measured on Cyph's vaults (2026-10-04): questions about his
# dissertation scored 0.25–0.51; cricket, weather, gym, email, news and file
# searches scored 0.70–0.82. 0.60 sits in the gap.
_NOTES_MAX_DISTANCE = float(os.getenv("ZERO_NOTES_MAX_DISTANCE", "0.60"))
_FEEDBACK_MAX_DISTANCE = 0.35   # a rating only steers genuinely similar questions

# Agents that produce context others enrich from. They run in the first parallel
# wave so dependents (career←research, code←brainstorm, study←research, ...) can
# read their bus output in the second wave. Keeps Phase 4's enrichment intact
# while still parallelising the common case.
_PRODUCER_AGENTS = {"research", "brainstorm", "schedule"}

# Persona switch trigger phrases
_PERSONA_SWITCH_TRIGGERS: dict[str, list[str]] = {
    "v": ["hey v", "switch to v", "activate v", "wake v", "v mode", "talk to v"],
    "zero": ["hey zero", "switch to zero", "activate zero", "wake zero", "zero mode", "talk to zero", "back to zero"],
}


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting so responses read as clean spoken text."""
    # Remove bold/italic (**text**, *text*, __text__, _text_)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    # Remove headers (## Heading)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    # Remove bullet/numbered list markers
    text = re.sub(r'^\s*[-*•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Remove backtick code
    text = re.sub(r'`{1,3}[^`]*`{1,3}', lambda m: m.group(0).replace('`',''), text)
    # Remove blockquotes
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TaskContext:
    """Shared context passed between CEO and agents."""
    user_input: str
    intent: IntentResult
    bus: ContextBus = field(default_factory=ContextBus)
    memory_id: str = ""   # cold-memory interaction id — what 👍/👎 attach to
    selected_agents: list[AgentManifest] = field(default_factory=list)
    agent_outputs: dict[str, Any] = field(default_factory=dict)
    final_response: str = ""
    model_used: str = ""
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# CEO Agent
# ---------------------------------------------------------------------------

class CEOAgent:
    """
    Plans tasks, dispatches to department agents, synthesises results.

    The CEO never executes domain actions itself — it only coordinates.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry = registry,
        intent_classifier: IntentClassifier = classifier,
    ) -> None:
        """
        Args:
            agent_registry: The live plugin registry.
            intent_classifier: The intent + risk classifier.
        """
        self._registry = agent_registry
        self._classifier = intent_classifier
        # Log which provider is active on startup
        provider = detect_provider()
        logger.info(f"[ceo] LLM provider: {provider.value}")

        # Wire up HIGH-risk confirmation handler.
        # Default = CLI mode (blocks on stdin). The phone bridge overrides this
        # with _api_confirm() so high-risk requests return a preview instead of hanging.
        self._classifier.set_confirmation_handler(self._cli_confirm)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def handle(self, user_input: str, confirmed: bool = False) -> TaskContext:
        """
        Process a user command end-to-end.

        Args:
            user_input: Raw command from voice/text/API.
            confirmed:  True when the caller has ALREADY obtained explicit user
                        approval for this exact request (e.g. the Telegram bot's
                        Yes button). Lets a HIGH-risk action through the gate for
                        this one call only. In API mode the gate otherwise always
                        denies, so without this a confirmation can never execute.

        Returns:
            TaskContext with final response and full execution trace.
        """
        start_ms = int(time.time() * 1000)
        logger.info(f"[ceo] Received: {user_input!r}")

        # 0a. Check for persona switch commands before anything else
        persona_switch = self._detect_persona_switch(user_input)
        if persona_switch:
            new_persona = persona_state.switch(persona_switch)
            greeting = new_persona.greeting
            ctx = TaskContext(
                user_input=user_input,
                intent=IntentResult(
                    action="switch_persona",
                    risk_level=RiskLevel.READ,
                    trigger_words=[],
                    raw_input=user_input,
                ),
            )
            ctx.final_response = greeting
            ctx.model_used = "persona_switch"
            ctx.total_duration_ms = int(time.time() * 1000) - start_ms
            hot_memory.add_user(user_input)
            hot_memory.add_zero(greeting)
            _log_action(ctx)
            return ctx

        # 0b. Snapshot the conversation BEFORE adding this turn, then save the input.
        #     Agents only ever received the bare current message, so any follow-up
        #     ("now add levels to it") was handled as a brand-new request — Forge
        #     built a second, unrelated game instead of editing the first.
        history = hot_memory.as_context_string(n=10)
        # The follow-up decision needs the PREVIOUS turn only. Judging it from all
        # ten entries meant one build hijacked every later question — and since hot
        # memory now survives restarts, it did so permanently.
        last_exchange = hot_memory.as_context_string(n=2)
        hot_memory.add_user(user_input)

        # 1. Intent classification + risk gate.
        # `confirmed` means the caller already got an explicit yes from Cyph for
        # this exact text, so classify (for the audit trail) but skip the gate.
        if confirmed:
            intent = self._classifier.classify(user_input)
            allowed = True
            logger.info(f"[ceo] Pre-confirmed by caller — gate bypassed: {user_input!r}")
        else:
            intent, allowed = self._classifier.gate(user_input)
        bus = ContextBus()   # fresh whiteboard for this request only
        if history:
            # Every agent already receives the bus, so this is how history reaches
            # them without changing the run(query, bus) contract.
            bus.publish("ceo", "recent_conversation", history)
        if last_exchange:
            bus.publish("ceo", "last_exchange", last_exchange)
        ctx = TaskContext(user_input=user_input, intent=intent, bus=bus)

        if not allowed:
            ctx.final_response = "Action cancelled — user did not confirm high-risk operation."
            ctx.total_duration_ms = int(time.time() * 1000) - start_ms
            _log_action(ctx)
            return ctx

        # 2. Select agents (bus passed so skill hints can be published thread-safely)
        agents = self._select_agents(user_input, intent, bus=bus)
        ctx.selected_agents = agents

        if not agents:
            # No specialist agent matched — CEO handles directly
            ctx.final_response = self._direct_response(user_input, intent)
            ctx.model_used = "direct"
            ctx.total_duration_ms = int(time.time() * 1000) - start_ms
            # Save to memory even for direct responses
            ctx.memory_id = self._save_to_memory(user_input, ctx.final_response, agents_used=[])
            _log_action(ctx)
            return ctx

        # 3. Dispatch to agents in two parallel waves: producers first (so the
        #    bus is populated), then dependents read that context. Agents within
        #    a wave run concurrently — a 3-agent query no longer waits ~3x.
        wave1, wave2 = self._plan_waves(agents)
        self._dispatch_parallel(wave1, user_input, ctx)
        self._dispatch_parallel(wave2, user_input, ctx)

        logger.info(f"[ceo] Bus after dispatch: {ctx.bus.summary_line()}")

        # 3b. External MCP tools — pull results from any configured external
        #     MCP servers whose tools match this query. Fast no-op when none
        #     are configured (the common case). Hermes borrow #2.
        self._run_mcp_tools(user_input, ctx)

        # 4. Synthesise final response
        ctx.final_response, synthesis_cost = self._synthesise(ctx)
        ctx.total_cost_usd += synthesis_cost
        ctx.total_duration_ms = int(time.time() * 1000) - start_ms

        # 5. Save the full interaction to all memory tiers
        agents_used = [a.name for a in agents]
        ctx.memory_id = self._save_to_memory(user_input, ctx.final_response, agents_used)

        # 5b. Skills (learned routes) are no longer created here. Learning from
        #     every answer meant learning from failures too: the broken cricket
        #     reply became a skill whose hint was "acknowledge inability to provide
        #     live scores". Routes are now learned only when Cyph 👍s the answer —
        #     see core/feedback.py.

        _log_action(ctx)
        logger.info(
            f"[ceo] Done in {ctx.total_duration_ms}ms — "
            f"agents={agents_used} "
            f"cost=${ctx.total_cost_usd:.6f}"
        )
        return ctx

    # ------------------------------------------------------------------
    # Planning: which agents to use?
    # ------------------------------------------------------------------

    @staticmethod
    def _build_needs_facts(text: str) -> bool:
        """
        True if a build references real-world / current information that Iris should
        fetch first (e.g. "dashboard of today's weather", "site about the latest AI news").

        Self-contained builds — games, calculators, generic tools — return False so
        they go straight to Forge without paying for a research round.

        Args:
            text: Raw user command.

        Returns:
            True when the build needs external facts before coding.
        """
        t = text.lower()
        signals = (
            "latest", "today", "current", "live ", "real-time", "realtime",
            "up to date", "up-to-date", "from the web", "real data", "actual data",
            "news", "weather", "stock", "price", "prices", "information about",
            "data about", "data on", "facts about", "research", "statistics",
            "recent", "this week", "trending",
        )
        return any(s in t for s in signals)

    def _select_agents(
        self, user_input: str, intent: IntentResult, bus: ContextBus | None = None
    ) -> list[AgentManifest]:
        """
        Select relevant agents via keyword index, then optionally rank with Claude.

        Checks the skill store first — if a skill from a previous successful
        multi-agent task matches, its agent_sequence is used directly (skipping
        registry lookup and LLM ranking) and a synthesis hint is published to
        the bus so _synthesise() can inject it into the prompt.

        Args:
            user_input: Raw user command.
            intent:     Classified intent.
            bus:        Per-request ContextBus (used to publish the skill hint).

        Returns:
            Ordered list of AgentManifest to invoke (may be empty).
        """
        # Build pipeline: Zero builds GAMES only — everything else is answered in
        # Telegram. "make me a snake game" goes to Forge alone, with Iris first only
        # when the game needs real-world facts (a quiz on this week's news).
        # History-aware: "make it faster" names no artifact and matched no keyword
        # list, so it used to reach NO agent at all and the CEO answered directly —
        # claiming it had edited the game when nothing had run.
        followup = is_build_followup(
            bus.get("last_exchange", "") if bus else "", user_input
        )
        if is_game_build(user_input) or is_game_fix(user_input) or followup:
            code_m = self._registry.get("code")
            if code_m is not None:
                chain: list[AgentManifest] = []
                # Fresh builds may need facts first; iteration edits the existing file.
                if is_game_build(user_input) and self._build_needs_facts(user_input):
                    research_m = self._registry.get("research")
                    if research_m is not None:
                        chain.append(research_m)   # wave 1: gather facts → bus
                chain.append(code_m)               # wave 2: Forge reads bus, builds/fixes
                logger.info(
                    f"[ceo] Build/iterate request → pipeline: {[m.name for m in chain]}"
                )
                return chain

        # Skill shortcut: if we've done this class of task before, reuse the plan.
        # Publishing to the bus (not self) is thread-safe for concurrent requests.
        try:
            from skills.skill_store import skill_store
            skill_hits = skill_store.find(user_input, top_k=1)
            if skill_hits:
                skill = skill_hits[0]
                manifests = [
                    m for name in skill.agent_sequence
                    if (m := self._registry.get(name)) is not None
                ]
                if manifests:
                    skill_store.increment_use(skill.id)
                    logger.info(
                        f"[ceo] Skill hit: {skill.name!r} "
                        f"(use #{skill.use_count + 1}, agents={skill.agent_sequence})"
                    )
                    if bus and skill.synthesis_hint:
                        bus.publish("ceo", "skill_hint", skill.synthesis_hint)
                    return manifests
        except Exception as exc:
            logger.debug(f"[ceo] Skill lookup failed (non-fatal): {exc}")

        candidates = self._registry.find(user_input, top_k=3)

        if not candidates:
            return []

        # If single clear match, use it directly (save model call)
        if len(candidates) == 1:
            logger.info(f"[ceo] Single agent match: {candidates[0].name}")
            return candidates

        # Multiple candidates — use LLM to pick the best one
        ranked = self._rank_agents_with_llm(user_input, candidates)
        logger.info(f"[ceo] LLM-ranked agents: {[a.name for a in ranked]}")
        return ranked  # Phase 4: run ALL matched agents; they share context via the bus

    def _rank_agents_with_llm(
        self, user_input: str, candidates: list[AgentManifest]
    ) -> list[AgentManifest]:
        """
        Ask the active LLM to rank candidate agents by relevance.

        Args:
            user_input: The user's command.
            candidates: Shortlisted agents from the keyword index.

        Returns:
            Reordered list, most relevant first.
        """
        agent_descriptions = "\n".join(
            f"- {m.name}: {m.description}" for m in candidates
        )
        prompt = (
            f"User command: {user_input}\n\n"
            f"Available agents:\n{agent_descriptions}\n\n"
            f"Reply with ONLY the agent names in order of relevance, "
            f"comma-separated, most relevant first. Example: research,career"
        )
        try:
            resp = chat(prompt, tier="fast", max_tokens=64)
            order = [n.strip() for n in resp.text.split(",")]
            name_to_manifest = {m.name: m for m in candidates}
            ranked = [name_to_manifest[n] for n in order if n in name_to_manifest]
            for m in candidates:
                if m not in ranked:
                    ranked.append(m)
            return ranked
        except Exception as exc:
            logger.warning(f"[ceo] Agent ranking failed, using keyword order: {exc}")
            return candidates

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self, manifest: AgentManifest, user_input: str, ctx: TaskContext
    ) -> Any:
        """
        Dynamically import and run an agent's run() function.

        Args:
            manifest: The agent's manifest.
            user_input: The user's command to pass to the agent.
            ctx: Shared task context (agents may read prior outputs).

        Returns:
            Agent output (dataclass, dict, or string).
        """
        entry = ZERO_ROOT / manifest.entry_point
        logger.info(f"[ceo] Dispatching → {manifest.name} ({entry})")

        # Sandboxed dispatch: run the agent in an isolated subprocess so a crash
        # or infinite loop can't take down the backend. Opt-in via ZERO_SANDBOX_AGENTS=true.
        try:
            from sandbox.sandbox import is_enabled, run_agent_sandboxed
            if is_enabled():
                try:
                    result = run_agent_sandboxed(str(entry), user_input)
                    logger.info(f"[ceo] Sandbox dispatch OK for {manifest.name}")
                    return result
                except Exception as sandbox_exc:
                    logger.warning(
                        f"[ceo] Sandbox failed for {manifest.name}, "
                        f"falling back in-process: {sandbox_exc}"
                    )
        except ImportError:
            pass  # sandbox module missing — use in-process silently

        try:
            spec = importlib.util.spec_from_file_location(manifest.name, entry)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load spec for {entry}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[manifest.name] = module
            spec.loader.exec_module(module)   # type: ignore[attr-defined]

            if not hasattr(module, "run"):
                raise AttributeError(f"Agent {manifest.name} has no run() function")

            # Pass the shared bus so agents can read each other's outputs.
            # Agents that haven't been updated yet accept bus=None gracefully.
            try:
                result = module.run(user_input, bus=ctx.bus)
            except TypeError:
                # Fallback: agent run() doesn't accept bus kwarg yet
                logger.debug(f"[ceo] {manifest.name} does not accept bus kwarg — calling without it")
                result = module.run(user_input)

            # Normalise to dict for synthesis
            if hasattr(result, "to_dict"):
                return result.to_dict()
            return result

        except Exception as exc:
            logger.error(f"[ceo] Dispatch failed for {manifest.name}: {exc}")
            log_error(manifest.name, "dispatch", exc, context=user_input)
            return {"error": str(exc), "agent": manifest.name}

    def _plan_waves(
        self, agents: list[AgentManifest]
    ) -> tuple[list[AgentManifest], list[AgentManifest]]:
        """
        Split selected agents into two dispatch waves.

        Wave 1: producer agents, plus any agent that doesn't enrich from a
        selected producer. Wave 2: agents that read a selected producer's bus
        output (so they run after wave 1 populates it). When no producer is in
        the selection, everything lands in wave 1 — one fully parallel pass.

        Args:
            agents: The selected agents (relevance-ordered).

        Returns:
            (wave1, wave2) — each preserves the input ordering.
        """
        selected = {a.name for a in agents}
        wave1: list[AgentManifest] = []
        wave2: list[AgentManifest] = []
        for a in agents:
            depends_on_producer = bool(
                set(a.collaborates_with) & selected & _PRODUCER_AGENTS
            )
            if a.name not in _PRODUCER_AGENTS and depends_on_producer:
                wave2.append(a)
            else:
                wave1.append(a)
        return wave1, wave2

    def _dispatch_parallel(
        self, wave: list[AgentManifest], user_input: str, ctx: TaskContext
    ) -> None:
        """
        Run a wave of agents concurrently and collect their outputs into ctx.

        Agent run() calls are I/O-bound (LLM HTTP), so threads give a near-linear
        speedup. The ContextBus is thread-safe; ctx mutations happen here on the
        calling thread after each future resolves, never inside the workers.

        Args:
            wave:       Agents to run in parallel (may be empty or single).
            user_input: The user's command.
            ctx:        Shared task context to populate.
        """
        if not wave:
            return

        def _collect(manifest: AgentManifest, output: Any) -> None:
            ctx.agent_outputs[manifest.name] = output
            if isinstance(output, dict):
                ctx.total_cost_usd += output.get("cost_usd", 0.0)

        if len(wave) == 1:
            _collect(wave[0], self._dispatch(wave[0], user_input, ctx))
            return

        with ThreadPoolExecutor(max_workers=len(wave)) as pool:
            futures = {
                pool.submit(self._dispatch, m, user_input, ctx): m for m in wave
            }
            for fut, manifest in futures.items():
                try:
                    _collect(manifest, fut.result())
                except Exception as exc:
                    logger.error(f"[ceo] Parallel dispatch failed for {manifest.name}: {exc}")
                    log_error(manifest.name, "parallel_dispatch", exc, context=user_input)
                    _collect(manifest, {"error": str(exc), "agent": manifest.name})

    def _run_mcp_tools(self, user_input: str, ctx: TaskContext) -> None:
        """
        Call matching tools from external MCP servers and inject into task context.

        Results appear in ctx.agent_outputs under a "mcp:server/tool" key so the
        synthesis prompt picks them up automatically alongside agent outputs.
        Instant no-op when no external servers are configured.

        Args:
            user_input: Current user query used for tool matching.
            ctx:        Shared task context to write results into.
        """
        from core.mcp_client import mcp_registry
        if mcp_registry.server_count() == 0:
            return

        tools = mcp_registry.find_tools(user_input, top_k=2)
        for tool in tools:
            key = f"mcp:{tool.server_name}/{tool.name}"
            logger.info(f"[ceo] Calling external MCP tool: {key}")
            try:
                result = mcp_registry.call_tool(
                    tool.server_name, tool.name, {"query": user_input}
                )
                if result:
                    ctx.agent_outputs[key] = {"response": result, "source": "mcp"}
            except Exception as exc:
                logger.warning(f"[ceo] MCP tool {key} failed: {exc}")

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def _synthesise(self, ctx: TaskContext) -> tuple[str, float]:
        """
        Combine agent outputs into a single, coherent final response using Claude.

        Args:
            ctx: Task context with all agent outputs populated.

        Returns:
            Tuple of (final_response_text, cost_usd).
        """
        if not ctx.agent_outputs:
            return "No agent produced output.", 0.0

        # Build short-circuit: if a builder agent actually wrote a file to disk
        # (e.g. Forge saving a web app to Zero Tech), confirm that cleanly instead
        # of letting the synthesis LLM regurgitate the raw code as "paste this".
        for output in ctx.agent_outputs.values():
            if isinstance(output, dict) and output.get("saved_path"):
                path = output["saved_path"]
                opened = output.get("opened")
                msg = f"Done — I built it and saved it to {path}. "
                msg += (
                    "I've opened it in your browser, so it should be on screen now. "
                    if opened else
                    "Open that file in your browser to run it. "
                )
                msg += "It's a single self-contained file, so you can double-click it anytime to run it again."
                ctx.model_used = "build"
                return msg, 0.0

        # One depth decision drives both the synthesis model and the self-fix
        # budget so they never drift apart. small→Haiku(1 pass), mid→Sonnet(2),
        # deep→Opus(3). Multi-agent / high-risk lifts a small request to mid.
        complex_hint = (
            len(ctx.agent_outputs) > 1 or ctx.intent.risk_level == RiskLevel.HIGH
        )
        level = assess_depth(ctx.user_input, complex_hint=complex_hint)
        tier = {"small": "fast", "mid": "capable", "deep": "deep"}[level]
        iters = iters_for(level)

        outputs_block = ""
        for agent_name, output in ctx.agent_outputs.items():
            if isinstance(output, dict) and "error" in output:
                outputs_block += f"\n[{agent_name} ERROR]\n{output['error']}\n"
            elif isinstance(output, dict):
                # Pick the richest text field available across all agents
                text = (
                    output.get("summary")
                    or output.get("response")
                    or output.get("explanation")
                    or output.get("findings")
                    or output.get("draft_body")
                    or str(output)
                )
                outputs_block += f"\n[{agent_name}]\n{text}\n"
            else:
                outputs_block += f"\n[{agent_name}]\n{output}\n"

        memory_context = self._load_memory_context(ctx.user_input)
        memory_block = f"Conversation so far:\n{memory_context}\n\n" if memory_context else ""

        # Include the shared bus so Claude can see cross-agent shared data
        bus_context = ctx.bus.as_context_string()
        bus_block = f"\n{bus_context}\n" if bus_context else ""

        # Active persona drives both the prompt wording and the system style.
        persona = persona_state.active
        system_prompt = persona.system_style

        # Inject skill hint if this query matched a previously learned skill.
        skill_hint = ctx.bus.get("skill_hint")
        skill_block = f"\nApproach note (from past success): {skill_hint}\n" if skill_hint else ""

        prompt = (
            f"{memory_block}"
            f"Cyph just said: {ctx.user_input!r}\n\n"
            f"Your agents found:\n{outputs_block}"
            f"{bus_block}"
            f"{skill_block}\n"
            f"Respond as {persona.name} — directly, naturally, no markdown. "
            f"Give the actual answer with real detail. Don't summarise the findings, deliver them. "
            f"{persona.delivery_note} "
            f"Use conversation history to stay consistent. "
            f"Never mention agent names or internal tools."
        )

        try:
            resp = chat(
                prompt,
                tier=tier,
                system=system_prompt,
                max_tokens=1024,
            )
            ctx.model_used = f"{resp.provider.value}/{resp.model}"
            draft = _strip_markdown(resp.text)
            # Build -> Grade -> Fix: Zero/V catch their own markdown leaks,
            # bot-tone and vague answers before Cyph ever sees them. The same
            # `iters` that picked the model tier above also caps the fix loop.
            improved, qinfo = grade_and_fix(
                ctx.user_input, draft, persona.system_style, persona.name,
                max_iters=iters,
            )
            return _strip_markdown(improved), resp.cost_usd + qinfo.get("cost_usd", 0.0)
        except Exception as exc:
            logger.error(f"[ceo] Synthesis failed: {exc}")
            log_error("ceo", "synthesise", exc, context=ctx.user_input)
            return str(list(ctx.agent_outputs.values())[0]), 0.0

    def _direct_response(self, user_input: str, intent: IntentResult) -> str:
        """
        Handle commands that don't match any agent — CEO responds directly.

        Includes recent conversation context from hot memory so the persona
        remembers what was said in prior turns of this session.

        Args:
            user_input: The user's command.
            intent: Classified intent.

        Returns:
            Response string.
        """
        memory_context = self._load_memory_context(user_input)
        memory_block = f"Conversation so far:\n{memory_context}\n\n" if memory_context else ""
        persona = persona_state.active
        prompt = (
            f"{memory_block}"
            f"Cyph just said: {user_input!r}\n\n"
            f"Respond as {persona.name}. Direct, natural, no markdown. "
            f"Give the real answer — don't meta-commentate or narrate yourself. "
            f"{persona.delivery_note} "
            f"Stay consistent with the conversation. Say it the way you'd say it out loud. "
            # No agent ran on this path, so nothing was actually done. With build
            # history in the prompt the model happily claimed it had just edited the
            # game ("I baked in higher frame rates") when no file was touched.
            f"IMPORTANT: no tools ran for this message — you have NOT done anything, "
            f"changed any file or built anything just now. Never claim you did. "
            f"If Cyph is asking for something to be done, say what you'll do, not that "
            f"it's done."
        )

        # No agents fired here, so a direct request is either small talk or a
        # deep-knowledge question — deep ones get Opus + the full fix budget,
        # everything else stays on the fast model with a single pass.
        level = assess_depth(user_input)
        tier = "deep" if level == "deep" else "fast"

        try:
            resp = chat(
                prompt,
                tier=tier,
                system=persona.system_style,
                max_tokens=512,
            )
            draft = _strip_markdown(resp.text)
            # Build -> Grade -> Fix on direct answers too.
            improved, _qinfo = grade_and_fix(
                user_input, draft, persona.system_style, persona.name,
                max_iters=iters_for(level),
            )
            return _strip_markdown(improved)
        except Exception as exc:
            logger.error(f"[ceo] Direct response failed: {exc}")
            log_error("ceo", "direct_response", exc, context=user_input)
            return f"I couldn't process that request. Error: {exc}"

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def _save_to_memory(self, user_input: str, response: str, agents_used: list[str]) -> str:
        """
        Save a completed interaction to all three memory tiers.

        Hot  = this session's RAM (immediate context for next message)
        Warm = Redis/fallback cache (survives restarts, expires after 1 week)
        Cold = ChromaDB vector store (permanent semantic memory)

        Args:
            user_input: What the user said.
            response: What Zero replied.
            agents_used: Which agents handled the request.
        """
        # Hot — add Zero's response to session RAM
        hot_memory.add_zero(
            response,
            metadata={"agents": agents_used},
        )

        # Warm — cache the interaction in Redis (survives restart, expires in 7 days)
        try:
            warm_memory.cache_interaction(
                user_input=user_input,
                zero_response=response,
                metadata={"agents": agents_used},
            )
        except Exception as exc:
            logger.warning(f"[ceo] Warm memory save failed: {exc}")

        # Cold — embed and store permanently in ChromaDB
        try:
            return cold_memory.store_interaction(
                user_input=user_input,
                zero_response=response,
                agents_used=agents_used,
            )
        except Exception as exc:
            logger.warning(f"[ceo] Cold memory save failed: {exc}")
            return ""

    def _load_memory_context(self, user_input: str) -> str:
        """
        Pull relevant past context to include in the synthesis prompt.

        Checks:
        1. Last 5 messages from hot memory (recent conversation flow)
        2. Semantically similar past interactions from cold memory

        Args:
            user_input: Current user query (used for semantic search).

        Returns:
            Formatted context string to inject into the LLM prompt.
        """
        context_parts: list[str] = []

        # Recent session context from hot memory — last 10 turns for full continuity
        recent = hot_memory.as_context_string(n=10)
        if recent:
            context_parts.append(f"Recent conversation:\n{recent}")

        # Relevant past interactions via hybrid recall — semantic (vector) fused
        # with exact-term (FTS5 keyword) so acronyms, names and IDs surface even
        # when embeddings miss them. RRF already ranks, so we take the top hits.
        try:
            hits = cold_memory.hybrid_search(
                collection="interactions",
                query=user_input,
                n_results=4,
            )
            if hits:
                relevant = "\n".join(f"- {h['text'][:200]}" for h in hits)
                if relevant:
                    context_parts.append(f"Relevant past context:\n{relevant}")
        except Exception as exc:
            logger.debug(f"[ceo] Cold memory search failed: {exc}")

        # Cyph's own notes (Obsidian vaults, PDFs). Gated on semantic distance: the
        # keyword index ORs every word, so every note "matches" every message, and
        # without a bar each request would ship dissertation excerpts to the cloud
        # model for nothing.
        try:
            notes = [
                h for h in cold_memory.hybrid_search("knowledge", user_input, n_results=8)
                if h.get("distance", 9.0) <= _NOTES_MAX_DISTANCE
            ][:4]
            if notes:
                context_parts.append("From Cyph's own notes (use these; they're his):\n" + "\n".join(
                    f"- [{(h.get('metadata') or {}).get('title', 'note')}] {h['text'][:700]}"
                    for h in notes))
        except Exception as exc:
            logger.debug(f"[ceo] Notes recall failed: {exc}")

        # How Cyph rated answers to similar questions — the feedback loop.
        try:
            rated = [h for h in cold_memory.search("feedback", user_input, n_results=3)
                     if h.get("distance", 9.0) <= _FEEDBACK_MAX_DISTANCE][:2]
            for h in rated:
                meta = h.get("metadata") or {}
                verdict = ("Cyph rated this answer 👍 — match what worked"
                           if meta.get("rating", 0) > 0 else
                           "Cyph rated this answer 👎 — don't repeat what went wrong")
                context_parts.append(
                    f"{verdict}. He asked: {h['text'][:200]!r}\n"
                    f"The answer was: {str(meta.get('answer', ''))[:700]}")
        except Exception as exc:
            logger.debug(f"[ceo] Feedback recall failed: {exc}")

        return "\n\n".join(context_parts)

    # ------------------------------------------------------------------
    # Persona switch detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_persona_switch(user_input: str) -> str | None:
        """
        Check if user is asking to switch personas.

        Args:
            user_input: Raw user command.

        Returns:
            Persona key ('v' or 'zero') if switch detected, else None.
        """
        normalized = user_input.strip().lower().rstrip('.,!?')
        for persona_key, triggers in _PERSONA_SWITCH_TRIGGERS.items():
            for trigger in triggers:
                if normalized == trigger or normalized.startswith(trigger + ' '):
                    # Don't switch if already on that persona
                    if persona_state.name == persona_key:
                        return None
                    return persona_key
        return None

    # ------------------------------------------------------------------
    # Confirmation handler (CLI mode)
    # ------------------------------------------------------------------

    def use_api_mode(self) -> None:
        """
        Switch to API-safe confirmation handler.

        In API/phone mode we cannot block on stdin. Instead of hanging,
        high-risk actions are denied and a preview is returned to the client
        so the user can confirm in the next message.
        """
        self._classifier.set_confirmation_handler(self._api_confirm)
        logger.info("[ceo] Switched to API confirmation mode (no stdin blocking)")

    @staticmethod
    def _api_confirm(intent: IntentResult) -> bool:
        """
        API-mode confirmation handler — always denies to prevent stdin hang.

        The CEO's final_response will contain the denial message with the
        preview so the phone/API client can show it to the user for confirmation.

        Args:
            intent: The classified high-risk intent.

        Returns:
            False — always. Prevents execution until explicit user confirmation.
        """
        logger.info(f"[ceo] HIGH-risk action blocked in API mode: {intent.raw_input!r}")
        return False

    @staticmethod
    def _cli_confirm(intent: IntentResult) -> bool:
        """
        Prompt the user in the terminal for HIGH-risk action confirmation.

        Args:
            intent: The classified high-risk intent.

        Returns:
            True if user typed 'yes', False otherwise.
        """
        print(f"\n{intent.confirmation_prompt}")
        try:
            answer = input("Confirm? [yes/no] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer == "yes"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

ceo = CEOAgent()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _log_action(ctx: "TaskContext") -> None:
    """
    Write a structured action log entry to logs/ceo_actions.jsonl.

    Args:
        ctx: Completed TaskContext with all fields populated.
    """
    import json
    from datetime import datetime, timezone

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "ceo_actions.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "ceo",
        "action_type": "handle",
        "input_summary": ctx.user_input[:120],
        "agents_used": [a.name for a in ctx.selected_agents],
        "risk_level": ctx.intent.risk_level.value if ctx.intent else "unknown",
        "outcome": ctx.final_response[:200] if ctx.final_response else "",
        "duration_ms": ctx.total_duration_ms,
        "cost_usd": ctx.total_cost_usd,
        "model": ctx.model_used,
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning(f"[ceo] Failed to write action log: {exc}")
