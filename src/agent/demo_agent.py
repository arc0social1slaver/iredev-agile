"""demo_agent.py — Interviewer agent smoke-test.

Run from any directory:
    python src/agent/demo_agent.py

Optional LangSmith tracing:
    export LANGCHAIN_TRACING_V2=true
    export LANGCHAIN_API_KEY=<your-langsmith-key>
    export LANGCHAIN_PROJECT=<your-project-name>
"""

import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root resolution — works regardless of CWD or how the script is
# invoked (python src/agent/demo_agent.py  OR  cd src/agent && python demo_agent.py)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # …/TOSEM-iReqDev

# Make sure src/ is on sys.path so bare `from src.X import Y` works
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Paths — all relative to project root, no hardcoded /Users/…
#
# Two separate configs:
#   AGENT_CONFIG_PATH  — LLM provider settings (type, model, api_base, …)
#                        read by LLMFactory inside BaseAgent
#   IREDEV_CONFIG_PATH — iReDev framework settings (knowledge_base, embedding,
#                        pg_connection, …) read by ConfigManager / KnowledgeModule
# ---------------------------------------------------------------------------
AGENT_CONFIG_PATH  = str(PROJECT_ROOT / "config" / "agent_config.yaml")
IREDEV_CONFIG_PATH = str(PROJECT_ROOT / "config" / "iredev_config.yaml")
PROMPT_PATH        = str(PROJECT_ROOT / "prompts" / "interviewer_profile.txt")
PG_CONN_STR        = "postgresql+psycopg://postgres:postgres@localhost:5432/iredev"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s - %(levelname)s - %(message)s",
)

# ---------------------------------------------------------------------------
# Imports (after sys.path is patched)
# ---------------------------------------------------------------------------
from src.agent.base import BaseAgent                          # noqa: E402
from src.memory import GlobalConversationLog, MemoryType      # noqa: E402
from src.orchestrator import ProcessPhase                     # noqa: E402
from src.config.config_manager import get_config_manager      # noqa: E402


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

class InterviewerAgent(BaseAgent):
    """Interviewer agent — elicits, clarifies, and documents stakeholder requirements.

    Memory: SHORT_TERM (conversation buffer seeded with the interviewer profile).
    The buffer accumulates each dialogue turn and is wiped via memory.refresh()
    once the interview record is exported.

    Knowledge: on each process() call, ThinkModule retrieves ELICITATION-phase
    snippets (5W1H, Socratic questioning, ISO 29148, …) from the shared
    KnowledgeModule and prepends them to the system context automatically.
    """

    def process(self, user_input: str) -> str:
        """Receive a stakeholder reply and generate the next interviewer turn.

        Args:
            user_input: Stakeholder response or initial project description.

        Returns:
            The interviewer's next question or follow-up.
        """
        print(f"\n[Agent: {self.name}] thinking...")

        knowledge_context = self.think.build_prompt_context(
            query=user_input,
            phase=ProcessPhase.ELICITATION,
            memory_context=self.memory.take(),
        )

        return self.generate_response(
            messages=[("user", user_input)],
            knowledge_context=knowledge_context,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        # Initialise config system BEFORE anything else so KnowledgeModule,
        # LLMFactory, and MemoryModule all read from the same loaded config.
        # Init iReDev config first so KnowledgeModule reads correct knowledge_base + embedding
        get_config_manager(IREDEV_CONFIG_PATH)

        log = GlobalConversationLog()

        agent = InterviewerAgent(
            name="Interviewer",
            prompt_path=PROMPT_PATH,
            pg_conn_str=PG_CONN_STR,
            config_path=AGENT_CONFIG_PATH,   # LLM provider (Ollama/api_base)
            memory_type=MemoryType.SHORT_TERM,
            global_log=log,
        )

        print(f"[System] Profile loaded:\n{agent.profile.prompt}\n")
        print("=" * 60)

        # -----------------------------------------------------------------
        # Simulated interview: project brief → multi-round elicitation
        # -----------------------------------------------------------------
        turns = [
            (
                "I need a web system where students can register for courses, "
                "view their timetable, and get notified when a seat opens up."
            ),
            (
                "The main users are undergraduate students and academic advisors. "
                "Advisors need to approve or reject registrations manually."
            ),
            (
                "We use Microsoft SSO for login. The system has to integrate with "
                "our existing student information system via REST API."
            ),
        ]

        for stakeholder_input in turns:
            print(f"\n[Stakeholder] {stakeholder_input}")
            response = agent.process(stakeholder_input)
            print(f"[{agent.name}] {response}")

        # Wipe short-term buffer once the interview session is complete
        agent.memory.refresh()
        print("\n[Memory] Short-term buffer cleared — ready for next session.")

        # -----------------------------------------------------------------
        # Rate limiter stats
        # -----------------------------------------------------------------
        limiter = agent.llm.rate_limiter
        print(f"\n--- Stats: {agent.name} ---")
        print(f"Total Requests  : {limiter.total_requests}")
        print(f"Total In Tokens : {limiter.total_input_tokens}")
        print(f"Total Out Tokens: {limiter.total_output_tokens}")
        print(f"Estimated Cost  : ${limiter.total_cost:.6f}")

        # -----------------------------------------------------------------
        # Export conversation log (written to <project_root>/logs/)
        # -----------------------------------------------------------------
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log.export(str(log_dir / "interview_run.json"))
        log.export(str(log_dir / "interview_run.txt"), fmt="text")
        print(f"\n[Log] Exported to {log_dir}/interview_run.{{json,txt}}")

        # Stop the knowledge watchdog cleanly on exit
        agent.knowledge.shutdown()

    except Exception as e:
        logging.exception(f"Demo failed: {e}")