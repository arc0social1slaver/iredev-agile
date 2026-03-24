from pathlib import Path


class ProfileModule:
    """Loads and exposes the agent's system prompt from a prompt file.

    Prompt files live in prompts/ at the project root (outside src/).
    The file is lazy-loaded on first access to avoid disk I/O at import time.

    Usage:
        profile = ProfileModule("prompts/interviewer_profile.txt")
        system_prompt = profile.prompt   # loaded once, cached afterwards
    """

    def __init__(self, prompt_path: str) -> None:
        """Set the path to the prompt file.

        Args:
            prompt_path: Relative or absolute path to the .txt prompt file.
        """
        self._path = Path(prompt_path)
        self._prompt: str = ""

    def load(self) -> str:
        """Read the prompt file from disk and cache the result.

        Returns:
            Full prompt text.

        Raises:
            FileNotFoundError: If prompt_path does not exist.
        """
        self._prompt = self._path.read_text(encoding="utf-8")
        return self._prompt

    @property
    def prompt(self) -> str:
        """Return the cached prompt, loading from disk on first access.

        Returns:
            Full prompt text.
        """
        if not self._prompt:
            self.load()
        return self._prompt