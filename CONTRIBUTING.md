# Contributing to Job Application Automation

First off, welcome to the project! This repository focuses on building local-first browser automation tools and reusable platform adapters. Because web pages change frequently, maintaining clean, modular code and good documentation is important.

---

## 🛠️ Code of Conduct & General Principles

1. **Keep it Modular:** Avoid tightly coupling UI interaction logic with backend state.
2. **Fail Fast, Log Everything:** Handle exceptions explicitly and provide descriptive logs.
3. **Protect the Main Branch:** Never commit directly to `main`. All changes should go through feature branches and Pull Requests.
4. **Document Significant Changes:** Architecture changes and research notes should be written in Markdown (`.md`) files.
 
---

## 🚀 Git Workflow Strategy

### Step 1: Fork and Clone

First, fork the repository to your own GitHub account and clone your fork locally:

```bash
git clone https://github.com/YOUR_USERNAME/internship-applier.git
cd internship-applier
```

### Step 2: Create a Virtual Environment

#### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

### Step 3: Create a Feature Branch

Never work directly on `main`.

```bash
git checkout -b feature/my-feature
```

Examples:

* `feature/wellfound-adapter`
* `fix/selector-bug`
* `docs/readme-update`

---

### Step 4: Check Your Changes

```bash
git status
```

---

### Step 5: Commit Your Work

```bash
git add .
git status
git commit -m "feat: add new platform adapter"
```

Examples:

* `feat: add Wellfound adapter`
* `fix: resolve selector parsing issue`
* `refactor: extract HumanActor into core module`
* `docs: improve README setup instructions`

---

### Step 6: Push Your Branch

```bash
git push origin feature/my-feature
```

---

### Step 7: Open a Pull Request

1. Go to GitHub.
2. Click **Compare & Pull Request**.
3. Explain what changed and why.
4. Submit the PR.

---

## 🚨 Emergency Commands

### "Where am I?"

```bash
git branch
```

### "What changed?"

```bash
git status
```

### "I broke something and want to discard local changes"

```bash
git restore .
```

### "I want to temporarily save my work"

```bash
git stash
```

Restore it later:

```bash
git stash pop
```

---

## First Contribution?

Don't worry if you've never contributed to open source before. Feel free to ask questions before opening a PR.

Good first issues are usually labeled:

* `good first issue`
* `documentation`
* `bug`
* `refactor`

Welcome aboard 🚀
