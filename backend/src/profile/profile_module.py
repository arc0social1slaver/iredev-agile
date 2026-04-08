from pathlib import Path


class ProfileModule:
    """Loads and exposes the agent's system prompt from a prompt file."""

    def __init__(self, prompt_path: str) -> None:
        """Set the path to the prompt file.

        Args:
            prompt_path: Relative or absolute path to a prompt file.
        """
        self._path = Path(prompt_path)
        self._prompt: str = ""

    def load(self) -> str:
        """Read the prompt file and cache the result.

        Returns:
            Full prompt text.

        Raises:
            FileNotFoundError: If prompt_path does not exist.
        """
        self._prompt = self._path.read_text(encoding="utf-8")
        return self._prompt

    @property
    def prompt(self) -> str:
        """Return the cached prompt or loading on first access.

        Returns:
            Full prompt text.
        """
        if not self._prompt:
            self.load()
        return self._prompt