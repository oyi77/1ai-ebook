---
name: ebook
description: AI Ebook Generator — create, generate, research, and export ebooks
level: 2
---

# AI Ebook Generator Skill

You have access to the `ebook-generator` MCP server which exposes 8 tools for managing the full ebook creation pipeline.

## Available MCP Tools

| Tool | Description | Required params |
|------|-------------|-----------------|
| `ebook_list_projects` | List all ebook projects with status | `limit` (optional, default 20) |
| `ebook_create_project` | Create a new ebook project | `title`, `idea` |
| `ebook_generate` | Start background generation for a project | `project_id` |
| `ebook_get_status` | Get generation status and progress | `project_id` |
| `ebook_get_export_info` | Get strategy, marketing kit, keywords, ad hooks, pricing, word count | `project_id` |
| `ebook_research_market` | Search Google Books + Open Library for competing ebooks | `query` |
| `ebook_list_files` | List all files in a project directory with sizes | `project_id` |
| `ebook_read_file` | Read a project file (markdown, JSON, text) | `project_id`, `filename` |

### `ebook_create_project` optional params
- `product_mode`: `lead_magnet` | `paid_ebook` | `bonus_content` | `authority` (default: `lead_magnet`)
- `target_language`: BCP-47 code, e.g. `en`, `id`, `es` (default: `en`)
- `chapter_count`: integer (default: 5)

### `ebook_read_file` filename examples
- `strategy.json`, `outline.json`, `toc.md`, `manuscript.md`
- `chapters/1.md`, `chapters/2.md`
- `cover/prompt.txt`
- `marketing_kit.json`

---

## Typical Workflows

### 1. Research → Create → Generate → Monitor → Export → Push to AdForge

```
1. Research the market
   ebook_research_market(query="productivity habits", language="en", max_results=10)

2. Create a project
   ebook_create_project(title="Atomic Habits for Entrepreneurs", idea="...", product_mode="paid_ebook", chapter_count=7)
   → returns project with id (e.g. 3)

3. Start generation
   ebook_generate(project_id=3)

4. Poll status until completed
   ebook_get_status(project_id=3)
   → check db_status and progress fields; repeat every 30–60s until status="completed"

5. Get export metadata
   ebook_get_export_info(project_id=3)
   → returns keywords, ad_hooks, suggested_price, word_count, audience, tone

6. Read generated content (optional)
   ebook_read_file(project_id=3, filename="manuscript.md")
   ebook_read_file(project_id=3, filename="strategy.json")

7. Push to AdForge landing page
   POST http://localhost:3000/api/landing
   {
     "name": "ebook-{project_id}",
     "theme": "dark",
     "product_name": "<title>",
     "price": "<suggested_price from export>",
     "pain_points": ["...", "..."],
     "benefits": ["...", "..."],
     "cta_primary": "Download Now",
     "cta_secondary": "Learn More"
   }
```

### 2. List and Inspect Existing Projects

```
ebook_list_projects(limit=10)
ebook_get_status(project_id=N)
ebook_list_files(project_id=N)
ebook_read_file(project_id=N, filename="outline.json")
```

### 3. Multi-language Ebook

```
ebook_create_project(
  title="...",
  idea="...",
  target_language="id",  # Indonesian
  product_mode="lead_magnet"
)
```

---

## Project Status Values

| Status | Meaning |
|--------|---------|
| `draft` | Created, not yet generating |
| `generating` | Pipeline running |
| `completed` | All pipeline stages done |
| `failed` | Pipeline error (check message field) |

Progress tracking: `ebook_get_status` returns `progress` (0–100) and `message` alongside `db_status`.

---

## Project File Layout

```
projects/{id}/
  strategy.json        ← audience, tone, goal
  outline.json         ← chapter list with word count targets
  toc.md               ← table of contents markdown
  manuscript.md        ← full assembled ebook
  manuscript.json      ← per-chapter word counts
  marketing_kit.json   ← keywords, ad_hooks, pricing, book_description
  qa_report.json       ← QA checks
  chapters/{n}.md      ← individual chapter files
  cover/cover.png      ← generated cover image
  cover/prompt.txt     ← AI prompt used for cover
  exports/ebook.docx   ← Word export
  exports/ebook.pdf    ← PDF export
```

---

## Service Endpoints

- **Streamlit UI**: http://ebook.aitradepulse.com (port 8501)
- **REST API**: http://localhost:8765
  - `GET /health`
  - `GET /api/projects`
  - `POST /api/projects` (requires `X-Api-Key` header)
  - `GET /api/projects/{id}`
  - `POST /api/projects/{id}/generate`
  - `GET /api/projects/{id}/status`
  - `GET /api/projects/{id}/export`
  - `GET /api/projects/{id}/download/{fmt}` — fmt: docx, pdf, epub

---

## AdForge Integration

After generation, push the landing page to AdForge:

```http
POST http://localhost:3000/api/landing
Content-Type: application/json

{
  "name": "ebook-{project_id}",
  "theme": "dark",
  "product_name": "{title}",
  "price": "{suggested_price}",
  "pain_points": ["{ad_hooks[0]}", "{ad_hooks[1]}"],
  "benefits": ["{keywords derived}"],
  "cta_primary": "Download Now",
  "cta_secondary": "Learn More"
}
```

Use `ebook_get_export_info` to populate `price`, `pain_points` (from `ad_hooks`), and `benefits` (from `keywords`).

---

## Notes

- Generation is async — always poll `ebook_get_status` after calling `ebook_generate`.
- `ebook_read_file` supports `.md`, `.json`, `.txt`, `.csv`, `.html` only.
- `cover_image_base64` in export info is a PNG encoded as base64 — render inline or save to file.
- The MCP server runs in-process (no HTTP hop) — calls are direct Python module invocations.
