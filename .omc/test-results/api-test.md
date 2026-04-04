# AI Ebook Generator REST API — End-to-End Test Report

**Date:** 2026-04-04  
**Server:** http://localhost:8765  
**Project ID:** 6  
**Tester:** Executor agent (automated)

---

## Test Results

### Step 1 — Health Check
**Command:** `curl -s http://localhost:8765/health`  
**Response:** `{"status":"ok","version":"1.0"}`  
**Result:** PASS

---

### Step 2 — List Projects (no auth)
**Command:** `curl -s http://localhost:8765/api/projects`  
**Response:** Array of 5 existing projects (IDs 1–5), all with `"status":"completed"`  
**Result:** PASS

---

### Step 3 — Create Test Project
**Command:** `POST /api/projects` with `X-API-Key: dev-key-change-me`  
**Payload:**
```json
{
  "title": "E2E Test Ebook",
  "idea": "A short guide on productivity hacks for remote workers",
  "product_mode": "lead_magnet",
  "target_language": "en",
  "chapter_count": 3
}
```
**Response:**
```json
{
  "id": 6,
  "title": "E2E Test Ebook",
  "idea": "A short guide on productivity hacks for remote workers",
  "product_mode": "lead_magnet",
  "target_language": "en",
  "chapter_count": 3,
  "status": "draft",
  "created_at": "2026-04-04 02:50:07",
  "updated_at": "2026-04-04 02:50:07"
}
```
**Generated project ID:** 6  
**Result:** PASS

---

### Step 4 — Get Project
**Command:** `GET /api/projects/6`  
**Response:** Project record returned with `status: draft`  
**Result:** PASS

---

### Step 5 — Trigger Generation
**Command:** `POST /api/projects/6/generate` with `X-API-Key: dev-key-change-me`  
**Response:** `{"project_id":6,"message":"Generation started"}`  
**Result:** PASS

---

### Step 6 — Poll Status Until Completed/Failed
**Polls run:** 30 (max 20 original + 10 additional + 5 final = 35 total over ~8.75 minutes)  
**Final polled status:** `generating` (never transitioned to `completed` or `failed`)  

**Observation:** All 3 chapters were generated on disk (files present), manuscript.md and manuscript.json were written, but the DB status remained stuck at `"generating"`. The `updated_at` timestamp never changed from `2026-04-04T09:50:12.161707` after the initial job start.  

**Root cause:** The orchestrator appears to complete all content generation (strategy, outline, chapters, manuscript) but fails to write the final status update to the database. No `qa_report.json` was produced, which suggests the pipeline stalls after the ManuscriptEngine stage and before or during QAEngine/ContentSafety finalization.  

**Result:** FAIL — DB status never reached `completed` despite full content generation on disk

---

### Step 7 — Get Export Info
**Command:** `GET /api/projects/6/export`  
**Response:**
```json
{
  "project_id": 6,
  "title": "E2E Test Ebook",
  "description": "Build an engaged email list of remote professionals...",
  "audience": "Remote workers including digital nomads...",
  "tone": "Conversational, empathetic, and action-oriented...",
  "keywords": [],
  "ad_hooks": [],
  "suggested_price": "$9.99",
  "word_count": 2562,
  "cover_image_base64": "",
  "product_mode": "lead_magnet"
}
```
**Notes:** Export info returned successfully from manuscript data. `cover_image_base64` is empty (cover PNG was not generated — cover dir exists but is empty). Keywords and ad_hooks arrays are empty.  
**Result:** PASS (endpoint responds) / PARTIAL — cover image missing, keywords/hooks empty

---

### Step 8 — Check DOCX Download Endpoint
**Command:** `HEAD /api/projects/6/download/docx` with `X-API-Key: dev-key-change-me`  
**Response:** `HTTP/1.1 405 Method Not Allowed` (Allow: GET)  
**Note:** HEAD method not allowed; endpoint requires GET. No exports directory was created, so a GET would likely 404.  
**Result:** FAIL — No DOCX generated (exports/ directory does not exist)

---

### Step 9 — Check Generated Files

#### `projects/6/`
```
total 48
drwxr-xr-x  chapters/
drwxr-xr-x  cover/           (empty — no cover.png)
-rw-r--r--  manuscript.json  (476 bytes)
-rw-r--r--  manuscript.md    (15,821 bytes)
-rw-r--r--  outline.json     (3,746 bytes)
-rw-r--r--  strategy.json    (1,690 bytes)
-rw-r--r--  toc.md           (1,657 bytes)
```

#### `projects/6/chapters/`
```
-rw-r--r--  1.md  (7,024 bytes)
-rw-r--r--  2.md  (6,408 bytes)
-rw-r--r--  3.md  (2,172 bytes)
```

#### `projects/6/exports/`
Directory does not exist — DOCX/PDF export was not run.

**Result:** PARTIAL — Core content files present; cover, exports, qa_report missing

---

### Step 10 — Read Chapter 1 and Strategy

**Chapter 1 (`chapters/1.md`) — first 50 lines:**  
Title: "Your Space, Your Rules: Setting Up Without the Pinterest Pressure"  
Content is substantive, well-written prose covering:
- The "good enough" workspace philosophy
- Digital decluttering without guilt
- 5-minute environmental reset ritual
- Gear priorities vs. aesthetic traps

**strategy.json:** Successfully read. Contains:
- `audience`: Remote workers, digital nomads, WFH professionals
- `pain_points`: 6 specific pain points identified
- `promise`: "Reclaim 2+ hours daily" framework
- `positioning`: Anti-perfectionist guide
- `tone`: Conversational, empathetic, action-oriented
- `goal`: Build engaged email list → pathway to premium coaching

**marketing_kit.json:** Does not exist  
**Result:** PASS for chapter content and strategy; FAIL for marketing_kit.json

---

## Generated Content — Word Counts

| Chapter | Title | Words |
|---------|-------|-------|
| 1 | Your Space, Your Rules: Setting Up Without the Pinterest Pressure | 1,168 |
| 2 | Time Bending: Managing Your Day When No One's Watching the Clock | 1,042 |
| 3 | The Human Stuff: Boundaries, Isolation, and Knowing When to Log Off | 352 |
| **Total** | | **2,562** |

**Note:** Chapter 3 is significantly shorter (352 words) compared to chapters 1–2 (~1,100 words each). This may indicate the AI generation was cut short or a word-count target was not met for the final chapter.

---

## Errors Encountered

| # | Error | Severity |
|---|-------|----------|
| 1 | DB status stuck at `generating` — never transitions to `completed` | High |
| 2 | `qa_report.json` not generated — QAEngine may not have run | High |
| 3 | Cover image not generated — `cover/` directory exists but empty | Medium |
| 4 | `exports/` directory not created — DOCX/PDF export not triggered | High |
| 5 | `marketing_kit.json` not generated | Low |
| 6 | `keywords` and `ad_hooks` arrays empty in export response | Low |
| 7 | Chapter 3 word count (352) far below chapters 1–2 (~1,100) | Medium |
| 8 | `HEAD /download/docx` returns 405 (minor — use GET) | Low |

---

## Overall Verdict

**PARTIAL PASS**

The pipeline successfully completes the content generation phases:
- Project creation, strategy planning, outline generation, and manuscript writing all work correctly.
- 3 chapters generated with good-quality prose content (2,562 words total).
- Export info endpoint returns meaningful metadata.

However, the pipeline has a critical defect in its finalization stage:
- The DB status never updates from `generating` to `completed` after all content is written.
- Downstream steps (QAEngine, ContentSafety, cover generation, DOCX export) appear not to run or fail silently.
- The job worker likely encounters an unhandled exception after ManuscriptEngine completes, causing it to stall without marking the project failed or completed.

**Recommendation:** Investigate the orchestrator/job worker for unhandled exceptions after the manuscript stage. Add error logging and ensure the job always transitions to `completed` or `failed` regardless of downstream step failures.
