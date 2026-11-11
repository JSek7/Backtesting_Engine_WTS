
from abc import ABC, abstractmethod

from models.models import Observation, QuoteAction



from abc import ABC, abstractmethod


class BaseBot(ABC):

    @abstractmethod
    def get_quotes(self, observation: Observation, memory: dict) -> tuple[dict[str, QuoteAction], dict]:
        """Return quotes for all assets and updated memory, recieves observation from Market and previous memory"""
        ...
