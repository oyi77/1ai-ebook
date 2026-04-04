import streamlit as st
from pathlib import Path
import sys
import os
import json
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(page_title="Integrations", page_icon="🔗", layout="wide")

from utils.mobile_css import inject_mobile_css
inject_mobile_css()

st.title("🔗 Integrations")
st.markdown("Connect to BerkahKarya Hub and adforge for publishing, notifications, and knowledge base sync.")

# ─── helpers ────────────────────────────────────────────────────────────────

def _get(url: str, headers: dict | None = None, timeout: int = 4):
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    except requests.exceptions.ConnectionError:
        return None, "Connection refused"
    except Exception as e:
        return None, str(e)

def _post(url: str, payload: dict, headers: dict | None = None, timeout: int = 8):
    try:
        r = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    except requests.exceptions.ConnectionError:
        return None, "Connection refused"
    except Exception as e:
        return None, str(e)

def status_badge(ok: bool) -> str:
    return "🟢 Online" if ok else "🔴 Offline"


# ════════════════════════════════════════════════════════════════════════════
# BK HUB
# ════════════════════════════════════════════════════════════════════════════

st.header("🏢 BerkahKarya Hub")

with st.expander("⚙️ Connection Settings", expanded=False):
    bk_url = st.text_input(
        "BK Hub URL",
        value=os.environ.get("BK_HUB_URL", "http://localhost:9099"),
        help="Set BK_HUB_URL env var to persist this.",
    )
    st.caption("Sub-services (n8n, WAHA, PaperClip) are configured in the Hub — no extra keys needed here.")

# Health check
col_status, col_refresh = st.columns([4, 1])
with col_refresh:
    if st.button("↻ Refresh", key="bk_refresh"):
        st.rerun()

status_code, health_data = _get(f"{bk_url}/health")
hub_online = status_code == 200

with col_status:
    st.markdown(f"**Hub status:** {status_badge(hub_online)}")

if hub_online and isinstance(health_data, dict):
    services = health_data.get("services", {})
    if services:
        st.markdown("**Service health:**")
        cols = st.columns(len(services))
        for col, (svc, info) in zip(cols, services.items()):
            ok = info.get("status") == "ok" if isinstance(info, dict) else False
            col.metric(svc.upper(), "🟢" if ok else "🔴")
    else:
        st.info("Hub is online — no service breakdown returned.")
elif not hub_online:
    st.warning(f"Hub unreachable at `{bk_url}`. Start with `cd ~/.openclaw/workspace/projects/berkahkarya-hub && ./start.sh`")

st.divider()

# ── Actions ─────────────────────────────────────────────────────────────────
st.subheader("📤 Push Ebook to PaperClip Knowledge Base")

try:
    from src.db.repository import ProjectRepository
    db_path = Path("data/ebook_generator.db")
    if db_path.exists():
        repo = ProjectRepository(str(db_path))
        completed = [p for p in repo.list_projects(limit=50) if p["status"] == "completed"]
    else:
        completed = []
except Exception:
    completed = []

if not completed:
    st.info("No completed ebooks yet. Generate one first.")
else:
    project_options = {f"#{p['id']} — {p.get('idea', '')[:60]}": p for p in completed}
    selected_label = st.selectbox("Select ebook", list(project_options.keys()), key="bk_project_select")
    selected_project = project_options[selected_label]

    col_push, col_alert = st.columns(2)

    with col_push:
        if st.button("📚 Push to PaperClip KB", disabled=not hub_online):
            project_dir = Path("projects") / str(selected_project["id"])
            manuscript_file = project_dir / "manuscript.md"
            outline_file = project_dir / "outline.json"

            if not manuscript_file.exists():
                st.error("Manuscript file not found for this project.")
            else:
                content = manuscript_file.read_text()
                title = "Ebook"
                if outline_file.exists():
                    try:
                        outline = json.loads(outline_file.read_text())
                        title = outline.get("best_title", title)
                    except Exception:
                        pass

                payload = {
                    "query": f"Store ebook: {title}",
                    "context": content[:8000],  # PaperClip query endpoint
                }
                code, resp = _post(f"{bk_url}/paperclip/query", payload)
                if code and code < 300:
                    st.success(f"✅ Pushed to PaperClip KB! Response: {str(resp)[:200]}")
                else:
                    st.error(f"❌ Failed ({code}): {str(resp)[:200]}")

    with col_alert:
        wa_number = st.text_input("WhatsApp number (with country code)", value="6282247006969", key="bk_wa_number")
        if st.button("📱 Send WhatsApp Alert", disabled=not hub_online):
            project_dir = Path("projects") / str(selected_project["id"])
            outline_file = project_dir / "outline.json"
            title = selected_project.get("idea", "Ebook")[:60]
            if outline_file.exists():
                try:
                    outline = json.loads(outline_file.read_text())
                    title = outline.get("best_title", title)
                except Exception:
                    pass

            payload = {
                "channels": ["whatsapp"],
                "message": f"✅ Ebook ready: *{title}*\nProject #{selected_project['id']} has been generated and is ready for export.",
                "number": wa_number,
            }
            code, resp = _post(f"{bk_url}/alert", payload)
            if code and code < 300:
                st.success("✅ WhatsApp alert sent!")
            else:
                st.error(f"❌ Alert failed ({code}): {str(resp)[:200]}")

st.divider()

# ── n8n Workflows ─────────────────────────────────────────────────────────
st.subheader("⚡ n8n Workflows")

col_list, col_trigger = st.columns(2)

with col_list:
    if st.button("📋 List Workflows", disabled=not hub_online):
        code, data = _get(f"{bk_url}/n8n/workflows")
        if code == 200 and isinstance(data, (dict, list)):
            workflows = data if isinstance(data, list) else data.get("data", [])
            if workflows:
                rows = []
                for wf in workflows[:20]:
                    rows.append({
                        "ID": wf.get("id", ""),
                        "Name": wf.get("name", ""),
                        "Active": "✅" if wf.get("active") else "⏸️",
                    })
                st.dataframe(rows, use_container_width=True)
            else:
                st.info("No workflows found.")
        else:
            st.error(f"Failed to fetch workflows ({code})")

with col_trigger:
    wf_id = st.text_input("Workflow ID to trigger", placeholder="e.g. ea2payRL0Q0zLgV5", key="bk_wf_id")
    wf_payload = st.text_area("Payload (JSON)", value="{}", height=80, key="bk_wf_payload")
    if st.button("▶️ Trigger Workflow", disabled=not hub_online or not wf_id):
        try:
            payload = json.loads(wf_payload)
        except json.JSONDecodeError:
            st.error("Invalid JSON payload")
        else:
            payload["workflowId"] = wf_id
            code, resp = _post(f"{bk_url}/n8n/trigger", payload)
            if code and code < 300:
                st.success(f"✅ Triggered! Response: {str(resp)[:300]}")
            else:
                st.error(f"❌ Failed ({code}): {str(resp)[:300]}")


# ════════════════════════════════════════════════════════════════════════════
# ADFORGE
# ════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("🚀 adforge")

with st.expander("⚙️ Connection Settings", expanded=False):
    adforge_url = st.text_input(
        "adforge URL",
        value=os.environ.get("ADFORGE_URL", "http://localhost:3000"),
        help="Set ADFORGE_URL env var to persist.",
        key="adforge_url_input",
    )
    adforge_key = st.text_input(
        "API Key",
        value=os.environ.get("ADFORGE_API_KEY", ""),
        type="password",
        help="Set ADFORGE_API_KEY env var to persist.",
        key="adforge_key_input",
    )

col_af_status, col_af_refresh = st.columns([4, 1])
with col_af_refresh:
    if st.button("↻ Refresh", key="af_refresh"):
        st.rerun()

headers = {}
if adforge_key:
    headers["Authorization"] = f"Bearer {adforge_key}"

af_code, af_data = _get(f"{adforge_url}/api/health", headers=headers)
adforge_online = af_code == 200

with col_af_status:
    st.markdown(f"**adforge status:** {status_badge(adforge_online)}")
    if not adforge_online:
        st.caption(f"Start with: `cd ~/projects/adforge && npm start`")

if completed:
    st.subheader("📄 Create Landing Page")
    af_label = st.selectbox("Select ebook", list(project_options.keys()), key="af_project_select")
    af_project = project_options[af_label]

    if st.button("🚀 Push to adforge", disabled=not adforge_online):
        project_dir = Path("projects") / str(af_project["id"])
        outline_file = project_dir / "outline.json"
        strategy_file = project_dir / "strategy.json"

        title = af_project.get("idea", "Ebook")[:80]
        subtitle = ""
        hook = ""
        tone = "professional"

        if outline_file.exists():
            try:
                outline = json.loads(outline_file.read_text())
                title = outline.get("best_title", title)
                subtitle = outline.get("best_subtitle", "")
            except Exception:
                pass
        if strategy_file.exists():
            try:
                strategy = json.loads(strategy_file.read_text())
                hook = strategy.get("hook", "")
                tone = strategy.get("tone", "professional")
            except Exception:
                pass

        payload = {
            "title": title,
            "subtitle": subtitle,
            "hook": hook,
            "tone": tone,
            "product_mode": af_project.get("product_mode", "lead_magnet"),
            "source": "1ai-ebook",
            "project_id": af_project["id"],
        }

        code, resp = _post(f"{adforge_url}/api/landing", payload, headers=headers)
        if code and code < 300:
            lp_id = resp.get("id", "") if isinstance(resp, dict) else ""
            st.success(f"✅ Landing page created! ID: {lp_id}")
            st.info("Open adforge to add your checkout link, connect Meta/TikTok ads, and publish.")
        else:
            st.error(f"❌ adforge returned {code}: {str(resp)[:200]}")
            st.caption(f"Make sure adforge is running at {adforge_url}")
