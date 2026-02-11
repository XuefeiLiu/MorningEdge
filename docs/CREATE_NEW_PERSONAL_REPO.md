# Create a New Personal Repo from This Codebase

Use one of the options below. Your `.env` is already in `.gitignore` and will **not** be copied into the new repo (create a new `.env` in the new folder from `.env.example`).

---

## Option A: Fresh copy (new history, no link to this repo)

Best if you want a clean repo with no connection to the original.

1. **Create a new empty repo on GitHub** (e.g. `your-username/morning-edge-personal`) — do **not** add a README or .gitignore.

2. **Copy the project and init new git** (run from the parent of `Morning_Edge`):

   ```bash
   # Replace NEW_REPO_NAME with your folder name, e.g. morning-edge-personal
   NEW_REPO_NAME="morning-edge-personal"
   cp -R Morning_Edge "$NEW_REPO_NAME"
   cd "$NEW_REPO_NAME"
   rm -rf .git
   git init
   git add .
   git commit -m "Initial commit from Morning_Edge codebase"
   git branch -M main
   git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

3. **In the new folder**, create your `.env` from the template:

   ```bash
   cp .env.example .env
   # Edit .env and add your API keys (ALPHA_VANTAGE_API_KEY, etc.)
   ```

---

## Option B: New remote (keep full history)

Use this if you want to keep all git history and only add a second remote to push to your personal repo.

1. **Create a new empty repo on GitHub** (e.g. `your-username/morning-edge-personal`).

2. **From inside Morning_Edge**, add your personal remote and push:

   ```bash
   cd /path/to/Morning_Edge
   git remote add personal git@github.com:YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u personal main
   ```

3. To clone the personal copy elsewhere later:

   ```bash
   git clone git@github.com:YOUR_USERNAME/YOUR_REPO_NAME.git
   cd YOUR_REPO_NAME
   cp .env.example .env
   # Edit .env with your keys
   ```

---

## After cloning or copying

- Copy `.env.example` to `.env` and fill in your keys (Supabase, Alpha Vantage, OpenAI, etc.).
- Backend: `pip install -r requirements.txt` then run as in README.
- Frontend: `cd frontend && npm install && npm run dev`.
- See main **README.md** for full setup and run instructions.
