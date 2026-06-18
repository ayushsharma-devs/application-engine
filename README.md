# Job Application Automation

A local-first tool for discovering opportunities and assisting with application workflows using browser automation and local LLMs.

## How it works

backend/  
├── orchestrator.py  (main handler, starts the program)
├── extractor.py  (scroll + parse listings)
├── memory.py  (dedupe + vaults/*.json)
├── resume_parser.py  (parses and stores details from your resume as a profile_context.json file)
├── applier.py  (maintains the applying pipeline)
├── config.py  (Configures your custom variables based on .env)
└── platforms/  
├── base.py  (Connects all platforms through abstract classes)
├── internshala.py  (Main handler for internshala, contains HumanActor, LLMSynthesizer, etc.)
└── platform_metadata.json (Contains all the metadata/selectors for each platform)


1. **Scan** — Opens your saved browser profile, walks search result pages, filters roles by keywords/stipend, and saves new listings to `vaults/internshala_vault.json`.
2. **Apply** — For jobs with status `Discovered`, opens each detail page, reads custom questions, asks Ollama for answers from your profile, and types them with human-like delays. Submit is **off by default** until you enable it.
3. **First run** — Creates automation_session/ —> Opens chromium —> Login manually to Internshala —> Cookies are stored —> internshala_vault.json is formed, profile_context.json is formed —> Future runs reuse session.

## Features

- Local-first architecture
- Human-in-the-loop workflow
- Resume context extraction
- Local LLM integration (Ollama)
- Persistent browser sessions
- Rate limiting and safety controls
- Modular platform adapters
- Extensible metadata-driven selectors
- No cloud dependencies
- Privacy-focused
## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) running locally with a model pulled (default: `llama3.2`)
- Chromium via Playwright

## Setup

### Clone and enter the project
`git clone https://github.com/ayushsharma-devs/internship-applier.git`
`cd "internship-applier"`

### Virtual environment (recommended)
python -m venv .venv
#### Windows

```
.venv\Scripts\activate
```

#### macOS/Linux

```
source .venv/bin/activate
```


pip install -r requirements.txt
python -m playwright install chromium

### Ollama

Default API: `http://localhost:11434`, model `llama3.2` (see `LLMResponseSynthesizer` in `applier.py`). Verify Ollama is up:
#### Start Ollama

```
ollama serve
ollama pull llama3.2
```



## Step by Step Manual
### 1. Create `.env`

1. Copy:

`cp .env.example .env`

(or manually create `.env` from `.env.example`)

2. Place your resume PDF in the project root.
3. Set:

```
RESUME_FILENAME=resume.pdf
```

This creates `profile_context.json` and `resume_context.txt` (both gitignored). The orchestrator loads `profile_context.json` automatically.

### 2. Log in to your target platform 

The first run opens a persistent browser profile in `automation_session/`. Log in manually when the window appears; cookies are reused on later runs.

## 3. Configure search 

Edit `SEARCH_URL_PRIMARY` in `.env` to match the filters you want (location, role, WFH, etc.).

### 4. Run

python orchestrator.py

## Safety switches

Before enabling real submissions, review these in code:

| Setting                    | Default                                                             | Purpose                                                                                              |
| -------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `ENABLE_SUBMIT`            | `False`                                                             | When `True`, clicks the final Submit button                                                          |
| `MAX_APPLICATIONS_PER_RUN` | `3`                                                                 | Cap applications per run                                                                             |
| `BLACK_LIST_KEYWORDS`      | `"unpaid", "free", "stipendless", "volunteer", "performance based"` | Specific keywords in job listings that you don't want to apply to                                    |
| `RESUME_FILENAME`          | `resume.pdf`                                                        | File path to your latest resume that you saved to your system                                        |
| `SEARCH_URL_PRIMARY`       | none                                                                | Your search link containing all your filters                                                         |
| `TARGET_PLATFORM`          | none                                                                | The platform you want to apply on (eventually will support platforms like LinkedIn, Wellfound, etc.) |

Human-like interaction (mouse movement, chunked typing, reading pauses, rate limits) lives in `HumanActor` inside `internshala.py`. Human-like interaction patterns (typing, pauses, mouse movement, and rate limiting) are implemented to provide a more natural workflow experience. Keep daily volume low to reduce account risk.


## What gets committed to Git

Private/local paths are listed in `.gitignore`:

- `*.pdf`, `profile_context.json`, `resume_context.txt`
- `vaults/`, `automation_session/`, `playwright_session/`
- `.venv/`, `.env`

After `git add .`, run `git status` and confirm no resume or profile files appear.

## Roadmap

- [ ] Make the architecture more modular
- [ ] LinkedIn adapter
- [ ] Wellfound adapter
- [ ] Plugin architecture 
- [ ] Resume optimization
- [ ] Human approval queue
- [ ] Dashboard and analytics
## Disclaimer

This project is a local-first browser automation and workflow assistance framework intended for educational and research purposes.

The software runs entirely on the user's machine and does not provide any hosted service or collect user data. Users are solely responsible for ensuring that their use of this software complies with applicable laws, regulations, and the terms of service of any third-party platforms they access.

This project is provided "AS IS", without warranty of any kind, express or implied, including but not limited to merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors or contributors be liable for any claim, damages, losses, or other liabilities arising from the use or misuse of this software.

No guarantees are made regarding compatibility, availability, accuracy, or continued functionality. External websites and services may change without notice.

Use responsibly and at your own risk.

## Responsible Usage

This software is intended as a human-assisted productivity tool. Users are encouraged to review opportunities, validate generated responses, and maintain reasonable application volumes.

The authors do not endorse the violation of any platform policies or applicable laws, and users are responsible for understanding and complying with such requirements.

## Privacy

This project operates locally and does not collect, transmit, or store user data outside the user's own environment.