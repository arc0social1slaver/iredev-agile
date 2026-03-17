from .base import BaseAgent
from typing import Optional


class Customer(BaseAgent):
    """Human Input to provide goal and comfirm"""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__("customer", config_path)

    def chat_with_interviewer(self, question: str):
        """Chat with the interviewer to provide goal and comfirm"""
        print(f"Interviewer: {question}")
        answer = input("Customer: ")
        return answer
