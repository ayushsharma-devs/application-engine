# platforms/base.py
from abc import ABC, abstractmethod
import json
from pathlib import Path
from playwright.async_api import Page

class BasePlatformAdapter(ABC):
    def __init__(self, platform_key: str, metadata_filename: str = "platform_metadata.json"):
        self.platform_key = platform_key
        self.selectors = self._load_selectors(metadata_filename)

    def _load_selectors(self, filename: str) -> dict:
        metadata_path = Path(__file__).parent / filename
        if not metadata_path.exists():
            raise FileNotFoundError(f"Platform selector metadata missing at: {metadata_path}")
        
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Pull the specific platform configuration out cleanly
        platform_data = data.get(f"{self.platform_key.upper()}_METADATA", {})
        return platform_data.get("selectors", {})

    @abstractmethod
    async def extract_jobs(self, page: Page, current_page_num: int) -> list[dict]:
        """
        Scrapes a search result index page and returns a standardized list of dicts:
        [{'id': '...', 'role': '...', 'company': '...', 'detail_url': '...'}]
        """
        pass

    @abstractmethod
    async def apply(self, page: Page, detail_url: str, profile_data: dict) -> str:
        """
        Navigates to the application detail page, synthesizes content, 
        interacts with the DOM, and returns an application execution status string.
        """
        pass