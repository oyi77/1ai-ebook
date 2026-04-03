import streamlit as st
from pathlib import Path
import sys
import os
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

st.set_page_config(page_title="Export & Download", page_icon="📥", layout="wide")

st.title("📥 Export & Download")
st.markdown("Download your generated ebooks in DOCX or PDF format")

from src.db.repository import ProjectRepository

db_path = Path("data/ebook_generator.db")

if not db_path.exists():
    st.info("No projects yet. Create one first!")
    st.page_link(
        "pages/2_✍️_Create_Ebook.py", label="→ Go to Create Ebook", icon="✍️"
    )
    st.stop()

repo = ProjectRepository(str(db_path))
projects = repo.list_projects(limit=20)
completed = [p for p in projects if p["status"] == "completed"]

if not completed:
    st.info("No completed ebooks yet. Generate one first!")
    st.page_link(
        "pages/2_✍️_Create_Ebook.py", label="→ Go to Create Ebook", icon="✍️"
    )
    st.stop()

st.markdown(
    f"### ✅ {len(completed)} Completed Ebook{'' if len(completed) == 1 else 's'}"
)

for project in completed:
    project_dir = Path("projects") / str(project["id"])

    docx_file = project_dir / "exports" / "ebook.docx"
    pdf_file = project_dir / "exports" / "ebook.pdf"
    manifest_file = project_dir / "exports" / "manifest.json"

    with st.expander(f"📚 {project['title']}", expanded=True):
        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown(f"**Idea:** {project['idea']}")
            st.markdown(
                f"**Chapters:** {project['chapter_count']} | **Language:** {project['target_language']}"
            )
            st.markdown(f"**Mode:** {project['product_mode']}")

            if manifest_file.exists():
                with open(manifest_file) as f:
                    manifest = json.load(f)
                st.markdown(f"**Generated:** {manifest.get('generated_at', 'Unknown')}")
                files_info = manifest.get("files", {})
                if "docx" in files_info:
                    st.markdown(
                        f"📄 DOCX: {files_info['docx'].get('size', 0) / 1024:.1f} KB"
                    )
                if "pdf" in files_info:
                    st.markdown(
                        f"📕 PDF: {files_info['pdf'].get('size', 0) / 1024:.1f} KB"
                    )

        with col2:
            st.markdown("**Download:**")

            if docx_file.exists():
                with open(docx_file, "rb") as f:
                    st.download_button(
                        label="📄 Download DOCX",
                        data=f.read(),
                        file_name=f"{project['title'].replace(' ', '_')}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_docx_{project['id']}",
                    )
            else:
                st.button(
                    "📄 DOCX (not found)",
                    disabled=True,
                    key=f"dl_docx_nf_{project['id']}",
                )

            if pdf_file.exists():
                with open(pdf_file, "rb") as f:
                    st.download_button(
                        label="📕 Download PDF",
                        data=f.read(),
                        file_name=f"{project['title'].replace(' ', '_')}.pdf",
                        mime="application/pdf",
                        key=f"dl_pdf_{project['id']}",
                    )
            else:
                st.button(
                    "📕 PDF (not found)",
                    disabled=True,
                    key=f"dl_pdf_nf_{project['id']}",
                )

            epub_file = project_dir / "exports" / "ebook.epub"
            if epub_file.exists():
                with open(epub_file, "rb") as f:
                    st.download_button(
                        label="📖 Download EPUB",
                        data=f.read(),
                        file_name=f"{project['title'].replace(' ', '_')}.epub",
                        mime="application/epub+zip",
                        key=f"dl_epub_{project['id']}",
                    )

        st.markdown("---")
        st.markdown("**Project Files:**")
        if project_dir.exists():
            cols = st.columns(4)
            file_idx = 0
            for f in sorted(project_dir.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    with cols[file_idx % 4]:
                        st.markdown(f"📄 `{f.name}`")
                        st.caption(f"{f.stat().st_size / 1024:.1f} KB")
                    file_idx += 1

        st.markdown("---")
        st.markdown("**🚀 Marketing:**")

        mk_file = project_dir / "marketing_kit.json"
        strategy_file = project_dir / "strategy.json"
        outline_file = project_dir / "outline.json"

        if st.button("🚀 Push to adforge", key=f"adforge_{project['id']}", help="Create a landing page + ads campaign in adforge"):
            marketing_kit = {}
            strategy = {}
            outline = {}

            if mk_file.exists():
                with open(mk_file) as f:
                    marketing_kit = json.load(f)
            if strategy_file.exists():
                with open(strategy_file) as f:
                    strategy = json.load(f)
            if outline_file.exists():
                with open(outline_file) as f:
                    outline = json.load(f)

            pain_points = strategy.get("pain_points", [])
            if isinstance(pain_points, list):
                pain_points_str = "\n".join(f"- {p}" for p in pain_points[:3])
            else:
                pain_points_str = str(pain_points)

            chapters = outline.get("chapters", [])
            benefits = [ch.get("title", "") for ch in chapters[:5] if ch.get("title")]
            benefits_str = "\n".join(f"- {b}" for b in benefits) if benefits else "Practical, actionable content"

            suggested_price = marketing_kit.get("suggested_price", "$9.99").replace("$", "").replace("Free", "0")

            payload = {
                "name": f"{project['title']} — AI Ebook",
                "theme": "dark",
                "product_name": project["title"],
                "price": suggested_price,
                "pain_points": pain_points_str,
                "benefits": benefits_str,
                "cta_primary": "Get Your Copy Now",
                "cta_secondary": "Download Free Preview",
            }

            adforge_url = os.environ.get("ADFORGE_URL", "http://localhost:3000")
            adforge_key = os.environ.get("ADFORGE_API_KEY", "")

            try:
                import requests
                headers = {"Content-Type": "application/json"}
                if adforge_key:
                    headers["Authorization"] = f"Bearer {adforge_key}"

                resp = requests.post(
                    f"{adforge_url}/api/landing",
                    json=payload,
                    headers=headers,
                    timeout=10,
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    lp_id = data.get("data", {}).get("id", "?")
                    st.success(f"✅ Landing page created in adforge! ID: {lp_id}")
                    st.info("💡 Open adforge to add your checkout link, connect Meta/TikTok ads, and publish.")
                else:
                    st.error(f"❌ adforge returned {resp.status_code}: {resp.text[:200]}")
                    st.info("Make sure adforge is running at " + adforge_url)
            except requests.exceptions.ConnectionError:
                st.error(f"❌ Cannot connect to adforge at {adforge_url}")
                st.info("Start adforge with `cd ~/projects/adforge && npm start`, then try again.")
            except Exception as e:
                st.error(f"❌ Error: {e}")
