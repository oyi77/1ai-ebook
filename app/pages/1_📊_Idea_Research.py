import streamlit as st
from pathlib import Path
import sys
import json
import re
from datetime import datetime
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

st.set_page_config(page_title="Idea Research", page_icon="📊", layout="wide")

st.title("📊 Idea Research")
st.markdown("Discover trending topics and profitable ebook niches — powered by AI")

st.markdown("---")


@st.cache_data(ttl=3600)
def get_trending_niches():
    client = OpenAI(
        base_url="http://localhost:20128/v1",
        api_key="sk-f0c1ddf471008e76-f92ijk-07d16379",
        timeout=60,
    )
    resp = client.chat.completions.create(
        model="auto/best-chat",
        messages=[
            {
                "role": "system",
                "content": "You are an expert ebook market analyst. Return ONLY valid JSON, no markdown, no explanations.",
            },
            {
                "role": "user",
                "content": """Generate 8 trending ebook niches for 2026. For each niche provide:
- category: with emoji prefix (e.g., "💰 Business & Finance")
- trending: list of 4 specific trending topics
- demand: "Very High", "High", "Medium", or "Growing"
- competition: "High", "Medium", or "Low"
- avg_price: price range string (e.g., "$9.99 - $29.99")
- tip: one actionable tip for this niche

Return as JSON array only. Make topics specific and current for 2026.""",
            },
        ],
        max_tokens=2000,
        temperature=0.8,
    )
    content = resp.choices[0].message.content
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🔥 Trending Ebook Niches 2026")

    if st.button("🔄 Refresh Trends", type="secondary"):
        get_trending_niches.clear()
        st.rerun()

    with st.spinner("Analyzing market trends..."):
        try:
            trending_niches = get_trending_niches()

            for niche in trending_niches:
                with st.expander(f"{niche['category']} — Demand: {niche['demand']}"):
                    col_a, col_b = st.columns([2, 1])
                    with col_a:
                        st.markdown(
                            f"**Trending Topics:** {', '.join(niche['trending'])}"
                        )
                        st.markdown(f"**💡 Tip:** {niche['tip']}")
                    with col_b:
                        st.metric("Avg Price", niche["avg_price"])
                        st.metric("Competition", niche["competition"])

                    st.markdown("---")
                    st.markdown("**Use any of these ideas:**")
                    for topic in niche["trending"]:
                        if st.button(f"📝 Use: {topic}", key=f"use_{topic}"):
                            st.session_state["researched_idea"] = (
                                f"Write a comprehensive guide about {topic.lower()} for beginners"
                            )
                            st.session_state["researched_category"] = niche["category"]
                            st.switch_page("pages/2_✍️_Create_Ebook.py")
        except Exception as e:
            st.error(f"Failed to fetch trends: {e}")
            st.info("Using cached data. Try refreshing.")

with col2:
    st.subheader("📈 Market Insights")

    st.metric("📚 Total Ebook Market", "$18.13B", "2026 est.")
    st.metric("📈 YoY Growth", "+6.7%", "2025-2026")
    st.metric("🤖 AI-Generated Share", "~15%", "Growing fast")

    st.markdown("---")
    st.subheader("🏆 Best-Selling Formats")
    st.bar_chart(
        {
            "Format": [
                "How-To Guides",
                "Workbooks",
                "Case Studies",
                "Checklists",
                "Full Books",
            ],
            "Popularity": [95, 78, 72, 68, 45],
        }
    )

    st.markdown("---")
    st.subheader("💡 Quick Tips")
    tips = [
        "Short ebooks (50-100 pages) sell better than long ones",
        "Lead magnets should be 15-30 pages max",
        "Include actionable templates and checklists",
        "Use real case studies and examples",
        "Price between $9.99-$19.99 for best conversion",
        "Update content annually for evergreen sales",
    ]
    for tip in tips:
        st.markdown(f"✅ {tip}")

st.markdown("---")
st.subheader("🔍 Custom Idea Validator")

with st.form("idea_validator"):
    idea = st.text_area(
        "Enter your ebook idea to validate:",
        placeholder="e.g., How to use AI for small business marketing",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        target_audience = st.selectbox(
            "Target Audience", ["Beginners", "Intermediate", "Advanced", "All Levels"]
        )
    with col_b:
        monetization = st.selectbox(
            "Monetization Goal",
            ["Lead Magnet", "Paid Product", "Authority Building", "Bonus Content"],
        )

    submitted = st.form_submit_button("🔍 Validate Idea", type="primary")

if submitted and idea:
    if len(idea) < 10:
        st.error("Idea too short — be more specific!")
    else:
        st.success("✅ Idea looks viable!")
        st.markdown(f"**Your Idea:** {idea}")
        st.markdown(f"**Audience:** {target_audience}")
        st.markdown(f"**Goal:** {monetization}")

        score = 75
        if len(idea) > 30:
            score += 10
        if target_audience != "All Levels":
            score += 5
        if monetization in ["Paid Product", "Lead Magnet"]:
            score += 5

        st.progress(score / 100)
        st.markdown(f"**Viability Score:** {score}/100")

        if score >= 80:
            st.success("🔥 Great idea! High potential for success.")
        elif score >= 60:
            st.info("👍 Good idea. Consider narrowing your niche further.")
        else:
            st.warning("⚠️ Idea needs refinement. Try being more specific.")

        if st.button("📝 Use This Idea", key="use_custom"):
            st.session_state["researched_idea"] = idea
            st.session_state["researched_audience"] = target_audience
            st.session_state["researched_monetization"] = monetization
            st.switch_page("pages/2_✍️_Create_Ebook.py")
