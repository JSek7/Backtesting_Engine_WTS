"""Local-only runner adapted from the organiser's timed BotRunner.

NOT a sandbox or a timeout mechanism. Run only code you trust on your machine.
"""
import time
from copy import deepcopy
from models.models import Observation, BotSubmission


class BotRunner:
    def __init__(self, bot_id, bot_factory):
        self.bot_id = bot_id
        self.bot_factory = bot_factory
        self.reset()

    def reset(self):
        # Reset instance attributes as well as explicit strategy memory.
        self.bot = self.bot_factory()
        self.memory = {}

    def run(self, observation: Observation) -> BotSubmission:
        # A failing call must not partially modify the saved memory dictionary.
        memory = deepcopy(self.memory)
        start = time.perf_counter_ns()
        result = self.bot.get_quotes(observation, memory)
        runtime = time.perf_counter_ns() - start
        if not isinstance(result, tuple) or len(result) != 2:
            raise ValueError("get_quotes must return (quotes, memory)")
        quotes, new_memory = result
        if not isinstance(quotes, dict) or not isinstance(new_memory, dict):
            raise ValueError("Both quotes and memory must be dictionaries")
        self.memory = new_memory
        return BotSubmission(self.bot_id, quotes, runtime)
