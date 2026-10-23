# Body composition tracking

I wanted to see how fast would it take to use an agent to build out an app. So I chose something that I needed: a tracking system that extracts data and puts it together in charts for my viewing. Its a small project so the overall quality is ok. Lots of design choices are guided more by my lack of $ than anything. But its an interesting start!


## Major Lessions:
Try to do things one macro step at a time. For instance, work with the agent to come up with an overall plan. Then, scaffold the project. If you prefer, the tests next. Agents arent smart enough to one shot the whole thing. And YOU arent diligent or expressive enough to articulate every single detail that you want in one breath. So take things one step at a time and you will realise that there are design blindspots along the way that you and the agent will work through.

## What this app does

Streamlit app for turning body-composition printout photos into structured data, saving rows to Google Sheets, and charting trends over time.

Extraction uses [NuExtract3](https://huggingface.co/numind/NuExtract3-W8A8) through a local **OpenAI-compatible vLLM** server. The app sends each image with a JSON schema derived from your Pydantic models so the model returns validated `BodyComposition` records (one image can contain multiple scans).

## Features

- **Data entry** — Upload a photo or point to a file on disk, preview the image, run extraction, edit fields, and add a record (with a required **name**) to Google Sheets.
- **Charts** — Load worksheet data and plot weight, body fat, muscle mass, and related metrics per person.
- **Diagnostics** — Optional trace logs and isolated subprocess checks for debugging Streamlit and Google Sheets integration.

Google Sheets access uses **OAuth desktop flow** (gspread). Spreadsheet name and credential paths come from environment variables.

## Prerequisites

- Python **3.13+** and [uv](https://docs.astral.sh/uv/)
- A Google Cloud **OAuth client** (desktop) and a spreadsheet the app can access
- For extraction: **vLLM** with `numind/NuExtract3-W8A8` in a separate environment (see [scripts/nuextract3_run](scripts/nuextract3_run))

## Setup

1. Install dependencies:

   ```bash
   uv sync --group dev
   ```

2. Copy environment template and fill in values (never commit `.env`):

   ```bash
   cp .env-template .env
   ```

   See [.env-template](.env-template) for `GCP_*`, `OPENAI_*`, and `EXTRACT_MODEL`.

3. Authenticate Google Sheets (once, or when tokens expire):

   ```bash
   uv run --env-file .env python scripts/gsheet_login.py
   ```

4. Start the inference server (separate terminal; conda env `llm` by default):

   ```bash
   bash scripts/nuextract3_run
   ```

   Default API URL: `http://localhost:8000/v1`.

5. Run the app:

   ```bash
   uv run --env-file .env streamlit run src/app.py
   ```

## Tests

```bash
uv run pytest tests/ -v
```

Integration tests (e.g. live extraction or Sheets) require a running vLLM server and configured credentials; they skip or mark when env is missing.

## Notes

- **HF cache on NTFS/exFAT:** Set `HF_HUB_DISABLE_SYMLINKS=1` in your shell if models live on a Windows-formatted drive; `nuextract3_run` runs cache repair before starting vLLM.
- **Secrets:** Keep OAuth JSON, tokens, and `.env` local. `.gitignore` excludes `.env`, `.secrets/`, and `token.json`.
