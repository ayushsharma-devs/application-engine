# Contributing to the AI Internship Applier

First off, welcome to the project! This repository is focused on building high-velocity, resilient automation engines for job application pipelines. Because we deal directly with live web forms, dynamic DOM structures, and anti-bot systems, maintaining strict engineering discipline is vital.

Please read through this guide carefully before opening an issue or submitting a Pull Request (PR).

---

## 🛠️ Code of Conduct & General Principles

1. **Keep it Modular:** Write clean, asynchronous code. Avoid tightly coupling UI interaction logic with backend data state.
2. **Fail Fast, Log Everything:** If a selector or network hook fails, handle the exception immediately and write descriptive error logging. No silent failures.
3. **Protect the Main Branch:** Never commit directly to `main`. All changes must go through an isolated feature branch and a reviewed Pull Request.

---

## 📋 Documentation Standards (.md Only)

All internal wikis, research deep-dives, architectural maps, and debugging briefs must be written strictly in **Markdown (`.md`)**. 
* Organize information logically using hierarchical headings (`##`, `###`).
* Upload the documentation for every PR in this google drive folder: [Internship applier documentation](https://drive.google.com/drive/folders/1kOKyQa-hvYxuwU8O6BaUL0tkban4Pgm5?usp=sharing) .
* Utilize code blocks with language syntax highlighting (e.g., \`\`\`python) for all code snippets or payload schemas.
* Bullet points should be concise, scannable, and data-dense.

---

## 🚀 Git Workflow Strategy

When you are assigned an issue or a bug to patch, follow these exact steps:
#### Step 1: Set Up Your Sandbox (Only Done Once)

First, you click the **"Fork"** button on GitHub to create a copy of the repository under your own GitHub account. Then, clone _your fork_ to your local machine. It is good practice to create a separate Python environment so that the dependencies for this project don't clash with your own dependencies:

```
#Use the following commands to set up a Python venv before cloning
cd your/working/directory
**Windows**: `python -m venv .venv`
**macOS / Linux**: `python3 -m venv .venv` 
  
- **macOS / Linux (Bash/Zsh)**: `source .venv/bin/activate`
- **Windows (Command Prompt)**: `.venv\Scripts\activate.bat`
- **Windows (PowerShell)**: `.\.venv\Scripts\Activate.ps1`
- **Git Bash (Windows)**: `source .venv/Scripts/activate`
```

Bash

```
git clone https://github.com/YOUR_USERNAME/ai-internship-applier.git
cd ai-internship-applier
git init #intialize your directory with git
```

#### Step 2: Create a Feature Branch (Before Writing Code)

Never write code on the `main` branch. A branch is just an isolated workspace. Create and switch to a new branch specifically for this text-input bug:

Bash

```
# This creates a new branch and switches your workspace into it
git checkout -b bugfix/text-input-bug
```

_Analogy:_ Think of this like saving a duplicate copy of a document as `Project_Draft_v2.docx` so you don't ruin the original copy while experimenting.

#### Step 3: Check Your Changes (While Coding)

As you modify files to fix the bug, check what files Git is tracking:

Bash

```
# Shows you which files have been modified or added
git status
```

#### Step 4: Stage and Commit Your Patch

Once the bug is fixed and your code works locally, you need to snapshot your progress.

Bash

```
# 1. Stage ALL of your modified files to be committed
git add .

# 2. Save the snapshot with a clear, descriptive message
git commit -m "fix: resolve erratic HTML tag injection in rich-text inputs"
```

#### Step 5: Push Your Branch to GitHub

Now, send your isolated local branch up to _your fork_ on GitHub:

Bash

```
git push origin bugfix/text-input-bug
```

#### Step 6: Submit the Pull Request (PR)

1. Go to the original repository page on GitHub.
    
2. You will see a prominent yellow banner that says: **"Compare & pull request"**. Click it.
    
3. Write a short description explaining how you fixed the bug, and click **"Create pull request"**.
    

### 🚨 Emergency Commands (When Things Go Wrong)


- **"Where am I?"** — If you forget what branch you are currently coding on:
Bash

 ` git branch`

*   **"I messed up my uncommitted code, reset me to safety!"** — If you write broken code and just want to wipe your local changes out and revert back to the last clean commit:

```
git checkout -- .
```