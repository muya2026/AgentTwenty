"""
AgentTwenty - Moltbook Engagement Bot
Main orchestrator script that coordinates scraping, analysis, engagement, and reporting.

Exit codes matter: this script used to swallow every error and always exit 0,
which made GitHub Actions show green while nothing actually happened.
Now:
  - a REAL engagement attempt that fails  -> exit 1
  - REQUIRE_REAL_ACTIONS=true (set in CI) -> exit 1 unless a real post and
    a real comment were actually published on Moltbook
"""

import os
import re
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Import components from src
try:
    from src.scraper import MoltbookScraper
    from src.analyzer import AgentAnalyzer
    from src.engager import AgentEngager
    from src.reporter import Reporter
except ImportError as e:
    logging.error(f"Failed to import modules: {e}")
    sys.exit(1)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AgentTwenty")

# Strict mode: when enabled (in GitHub Actions), the run only succeeds if the
# agent really published on Moltbook — no MOCK fallbacks allowed.
STRICT = os.getenv("REQUIRE_REAL_ACTIONS", "false").strip().lower() in {"1", "true", "yes"}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _is_real_target(post: dict) -> bool:
    """A post is a valid comment target only if it's a real API post (UUID id)."""
    return bool(post) and not post.get("mock") and bool(UUID_RE.match(str(post.get("id") or "")))


def main() -> int:
    """Main orchestration function for AgentTwenty daily operations."""
    logger.info("🚀 AgentTwenty Starting Daily Operation...")
    if STRICT:
        logger.info("🔒 STRICT mode (REQUIRE_REAL_ACTIONS): mock fallbacks will fail the run.")

    # Initialize Components (a config error here must fail loudly, not traceback)
    try:
        scraper = MoltbookScraper()
        analyzer = AgentAnalyzer()
        engager = AgentEngager()
        reporter = Reporter()
    except Exception as e:
        logger.error(f"❌ Failed to initialize components: {e}")
        if STRICT:
            logger.error("   → Check that QWEN_API_KEY and/or GEMINI_API_KEY repo secrets are set.")
        return 1

    # In strict mode, without a Moltbook key nothing real can happen — fail fast.
    if STRICT and not engager.moltbook_api_key:
        logger.error("❌ STRICT mode requires MOLTBOOK_API_KEY, but it is not configured.")
        logger.error("   → Add it under Settings → Secrets and variables → Actions.")
        return 1

    current_date = datetime.now().strftime("%Y-%m-%d")
    posts = []
    analysis_text = ""
    comment_status = "skipped"
    post_status = "not_attempted"

    # Step 1: Scrape Data
    try:
        logger.info("📡 Scraping Moltbook for trending posts...")
        posts = scraper.fetch_trending_posts()
        if not posts:
            logger.warning("No posts retrieved.")
        else:
            mock_count = sum(1 for p in posts if p.get("mock"))
            logger.info(f"✅ Fetched {len(posts)} posts ({len(posts) - mock_count} real, {mock_count} mock).")
    except Exception as e:
        logger.error(f"❌ Scraping failed: {e}")

    # Step 2: Analyze Data
    try:
        if posts:
            logger.info("🧠 Analyzing posts with Qwen Coder...")
            analysis_text = analyzer.analyze_posts(posts)
            logger.info("✅ Analysis complete.")
        else:
            logger.warning("⚠️ No posts to analyze. Skipping analysis step.")
            analysis_text = "No data available for analysis today."
    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}")
        analysis_text = "Analysis failed due to an error."

    # Step 3: Engage (Comment & Post)
    try:
        logger.info("💬 Generating engagement content...")

        # Comment on the first REAL post (never on mock ids like "post_001")
        real_targets = [p for p in posts if _is_real_target(p)]
        if real_targets:
            target = real_targets[0]
            logger.info(f"   Target post: {target.get('id')} by @{target.get('author', {}).get('username')}")
            comment = engager.generate_comment(target.get('content', ''))
            logger.info(f"Generated Comment: {comment[:50]}...")
            comment_status = engager.comment_on_moltbook(post_id=target['id'], comment=comment)
            if comment_status == "failed":
                logger.error("❌ Real comment attempt FAILED (see API error above).")
        elif not posts:
            logger.info("No posts to comment on.")
        else:
            logger.warning("⚠️ No REAL posts available to comment on (only mock data). Skipping comment.")

        # Generate Daily Post
        daily_post = engager.generate_daily_post(analysis_text)
        logger.info(f"Generated Daily Post: {daily_post[:50]}...")
        post_status = engager.post_to_moltbook(daily_post)
        if post_status == "failed":
            logger.error("❌ Real post attempt FAILED (see API error above).")
        elif post_status == "mock":
            logger.warning("⚠️ Daily post NOT published — running in MOCK mode (no MOLTBOOK_API_KEY).")

    except Exception as e:
        logger.error(f"❌ Engagement failed: {e}")
        post_status = "failed"

    # Step 4: Report
    try:
        logger.info("📝 Generating Markdown report...")
        report_path = reporter.generate_markdown_report(analysis_text, current_date)
        logger.info(f"✅ Report saved to: {report_path}")

        logger.info("📤 Sending Telegram report...")
        reporter.send_telegram_report(report_path)

        logger.info("📧 Sending Email report...")
        reporter.send_email_report(report_path, analysis_text)

        logger.info("✅ Reporting cycle complete.")
    except Exception as e:
        logger.error(f"❌ Reporting failed: {e}")

    # ---- Final verdict -------------------------------------------------
    exit_code = 0

    if post_status == "failed":
        logger.error("❌ The daily post was attempted against the real API and FAILED.")
        exit_code = 1
    if comment_status == "failed":
        logger.error("❌ The comment was attempted against the real API and FAILED.")
        exit_code = 1

    if STRICT:
        if not posts or all(p.get("mock") for p in posts):
            logger.error("❌ STRICT: no REAL posts were fetched from Moltbook (scraper fell back to mock data).")
            exit_code = 1
        if post_status != "posted":
            logger.error(f"❌ STRICT: daily post was not published (status={post_status}).")
            exit_code = 1
        if comment_status != "posted":
            logger.error(f"❌ STRICT: comment was not published (status={comment_status}).")
            exit_code = 1

    if exit_code:
        logger.error("🏁 AgentTwenty finished with ERRORS (run marked as failed).")
    else:
        logger.info("🏁 AgentTwenty Daily Operation Finished.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
