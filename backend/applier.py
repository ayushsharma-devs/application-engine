# applier.py
import json
import os
from playwright.async_api import Page

class ApplicationPipeline:
    def __init__(self, page: Page, profile_data: dict):
        self.page = page
        self.profile_data = profile_data
        self.vault_path = 'vaults/internshala_vault.json'

    async def run_pipeline(self, url: str, adapter: any) -> str:
        """Coordinates the application transaction via the selected platform adapter."""
        # Cleanly load specific selectors onto the adapter dynamically
        adapter.selectors = self._load_platform_selectors(adapter.platform_key)
        
        # Delegate the actual heavy-lifting to the specialized platform code
        execution_status = await adapter.apply(self.page, url, self.profile_data)
        
        # Log transactions to memory vaults exactly like your legacy framework did
        self._write_to_vault(url, execution_status, adapter.platform_key)
        
        return execution_status

    def _load_platform_selectors(self, platform_key: str) -> dict:
        # Mock or pull from your centralized config JSON paths
        return {} 

    def _write_to_vault(self, url: str, status: str, platform: str):
        """Maintains the local JSON audit records exactly like your legacy setup."""
        if not os.path.exists(self.vault_path):
            records = []
        else:
            with open(self.vault_path, 'r') as f:
                try:
                    records = json.load(f)
                except json.JSONDecodeError:
                    records = []

        records.append({
            "url": url,
            "status": status,
            "platform": platform,
            "timestamp": "2026-05-31"  # Or your live datetime string
        })

        with open(self.vault_path, 'w') as f:
            json.dump(records, f, indent=4)
        print(f"[Memory] Successfully wrote {len(records)} total records to '{self.vault_path}'.")