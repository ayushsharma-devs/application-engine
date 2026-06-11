import os
from pathlib import Path
from dotenv import load_dotenv
# Load environment variables cleanly (using standard library or python-dotenv)
# For a zero-dependency clone, you can parse it or require python-dotenv in requirements.txt
BASE_DIR: Path = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

class Settings:
    blacklist_keywords= {"unpaid", "free", "stipendless", "volunteer", 
            "performance based"}
    ENABLE_SUBMIT: bool = os.getenv("ENABLE_SUBMIT", "False").lower() in ("true", "1")
    MAX_APPLICATIONS: int = int(os.getenv("MAX_APPLICATIONS_PER_RUN", 3))
    RESUME_INPUT: str = os.getenv("RESUME_FILENAME", "resume.pdf")
    OLLAMA_HOST: str = os.getenv("http://localhost:11434")
    # Auto-resolve absolute paths to prevent execution location bugs
    BLACK_LISTKEYWORDS: str = os.getenv("BLACK_LIST_KEYWORDS",blacklist_keywords)
    RESUME_PATH: Path = BASE_DIR / RESUME_INPUT
    SEARCH_URL_INTERNSHALA: str = os.getenv("SEARCH_URL_INTERNSHALA", "https://internshala.com/fresher-jobs/work-from-home/")

    _raw_platforms: str = os.getenv("TARGET_PLATFORMS", "internshala")
    TARGET_PLATFORMS: list[str] = [p.strip().lower() for p in _raw_platforms.split(",") if p.strip()]
    OLLAMA_MODEL: str = os.getenv("llama3.2")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", 0.3))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", 250))
    
    @classmethod
    def validate_workspace(cls):
        """Runs a diagnostic check before launching Playwright or Ollama loops."""

        if not cls.RESUME_PATH.exists():
            print(f"❌ CRITICAL ERROR: Target resume file not found at '{cls.RESUME_PATH}'")
            print("Please ensure you placed your PDF in the root folder and updated your local .env file.")
            return False
        return True