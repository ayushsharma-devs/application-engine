# Internship Scraper

A local automation tool that scans [Internshala](https://internshala.com) for relevant internships, stores discoveries in a local vault, and (optionally) fills application forms using your resume context and a local LLM (Ollama). Runs entirely on your machine — browser session, job database, and resume data stay local.

## How it works

orchestrator.py
├── Scan phase → extractor.py (scroll + parse listings)
│   memory.py (dedupe + vaults/*.json)
└── Apply phase → applier.py (form inspect → Ollama answers → HumanActor fills form)

1. **Scan** — Opens your saved browser profile, walks search result pages, filters roles by keywords/stipend, and saves new listings to `vaults/internshala_vault.json`.
2. **Apply** — For jobs with status `Discovered`, opens each detail page, reads custom questions, asks Ollama for answers from your profile, and types them with human-like delays. Submit is **off by default** until you enable it.

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) running locally with a model pulled (default: `llama3.2`)
- Chromium via Playwright

## Setup

### Clone and enter the project
cd "internship scraper"

### Virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate # Windows
source .venv/bin/activate # macOS / Linux


pip install -r requirements.txt
playwright install chromium

### Ollama

Default API: `http://localhost:11434`, model `llama3.2` (see `LLMResponseSynthesizer` in `applier.py`). Verify Ollama is up:

ollama pull llama3.2
ollama serve

## Step by Step Manual
### 1. Resume → profile context

Place your resume PDF in the project root and set the filename in `.env.example` file and rename it to `.env`, then add the file name of your resume:

`RESUME_FILENAME=resume.pdf`

This creates `profile_context.json` and `resume_context.txt` (both gitignored). The orchestrator loads `profile_context.json` automatically.

### 2. Log in to Internshala (one time)

The first run opens a persistent browser profile in `automation_session/`. Log in manually when the window appears; cookies are reused on later runs.

## 3. Configure search 

Edit `SEARCH_URL_LINKEDIN` in `.env` to match the filters you want (location, role, WFH, etc.).

### 4. Run

python orchestrator.py

## Project layout

| File                  | Role                                                         |
| --------------------- | ------------------------------------------------------------ |
| `orchestrator.py`     | Entry point: scan pages, then apply pipeline                 |
| `extractor.py`        | Scroll listing pages and parse internship cards              |
| `memory.py`           | Load/save `vaults/{platform}_vault.json`, dedupe by job ID   |
| `applier.py`          | Form inspection, Ollama Q&A, human-like input (`HumanActor`) |
| `resume_parser.py`    | PDF → cleaned text → `profile_context.json`                  |
| `vaults/`             | Local job database (gitignored)                              |
| `automation_session/` | Persistent browser profile / login (gitignored)              |
| `config.py`           | Loads all your custom settings from .env                     |

## Safety switches

Before enabling real submissions, review these in code:

| Setting                    | Default                                                             | Purpose                                                                                              |
| -------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `ENABLE_SUBMIT`            | `False`                                                             | When `True`, clicks the final Submit button                                                          |
| `MAX_APPLICATIONS_PER_RUN` | `3`                                                                 | Cap applications per run                                                                             |
| `BLACK_LIST_KEYWORDS`      | `"unpaid", "free", "stipendless", "volunteer", "performance based"` | Specific keywords in job listings that you don't want to apply to                                    |
| `RESUME_FILENAME`          | `resume.pdf`                                                        | File path to your latest resume that you saved to your system                                        |
| `SEARCH_URL_INTERNSHALA`   | https://internshala.com/fresher-jobs/work-from-home/                | Your Internshala search link containing all your filters                                             |
| `TARGET_PLATFORM`          | internshala                                                         | The platform you want to apply on (eventually will support platforms like LinkedIn, Wellfound, etc.) |

Human-like interaction (mouse movement, chunked typing, reading pauses, rate limits) lives in `HumanActor` inside `applier.py`. Keep daily volume low to reduce account risk.


## What gets committed to Git

Private/local paths are listed in `.gitignore`:

- `*.pdf`, `profile_context.json`, `resume_context.txt`
- `vaults/`, `automation_session/`, `playwright_session/`
- `.venv/`, `.env`

After `git add .`, run `git status` and confirm no resume or profile files appear.

## Disclaimer

Automating job applications may violate a platform’s terms of service. Use at your own risk, keep volumes reasonable, and prefer manual review until you trust the pipeline’s answers.
