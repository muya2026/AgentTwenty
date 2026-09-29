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


# Secrets that must never contain whitespace/newlines (classic copy-paste issue:
# a trailing newline in a secret makes requests raise "Invalid header value").
_TOKEN_VARS = (
    "MOLTBOOK_API_KEY", "QWEN_API_KEY", "GEMINI_API_KEY",
    "GROQ_API_KEY", "GROQAPI", "GROQ",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
)
_TEXT_VARS = (
    "SMTP_EMAIL", "SMTP_PASSWORD", "RECIPIENT_EMAIL", "SMTP_SERVER", "MOLTBOOK_SUBMOLT",
)


def _sanitize_env() -> None:
    """Auto-clean stray whitespace/newlines out of configured secrets."""
    for name in _TOKEN_VARS:
        value = os.environ.get(name)
        if value is None:
            continue
        cleaned = re.sub(r"\s+", "", value)
        if cleaned != value:
            logger.warning(
                f"⚠️ {name} contained whitespace/newlines — cleaned automatically "
                f"(length {len(value)} → {len(cleaned)}). "
                "Please re-save the secret without spaces."
            )
            os.environ[name] = cleaned
    for name in _TEXT_VARS:
        value = os.environ.get(name)
        if value is not None and value.strip() != value:
            os.environ[name] = value.strip()
            logger.warning(f"⚠️ {name} had surrounding whitespace — trimmed.")


def _log_key_diagnostics() -> None:
    """Log SAFE diagnostics about key shapes (never the values themselves)."""
    mk = os.environ.get("MOLTBOOK_API_KEY")
    if mk:
        logger.info(
            f"MOLTBOOK_API_KEY: length={len(mk)}, "
            f"starts_with_moltbook_={mk.startswith('moltbook_')}"
        )
        if not mk.startswith("moltbook_"):
            logger.error("❌ MOLTBOOK_API_KEY does NOT start with 'moltbook_' — "
                         "it looks like a placeholder or wrong value. Re-save the secret.")
    else:
        logger.warning("MOLTBOOK_API_KEY is not set.")
    qk = os.environ.get("QWEN_API_KEY")
    logger.info(f"QWEN_API_KEY: length={len(qk) if qk else 0}")
    gk = os.environ.get("GEMINI_API_KEY")
    logger.info(f"GEMINI_API_KEY: length={len(gk) if gk else 0} (fallback engine; project currently denied by Google)")
    rk = (os.environ.get("GROQ_API_KEY") or os.environ.get("GROQAPI")
          or os.environ.get("GROQ"))
    logger.info(f"GROQ key: length={len(rk) if rk else 0} "
                f"(free tier — PRIMARY engine; accepts GROQ_API_KEY/GROQAPI/GROQ)")
    if not rk:
        logger.warning("❌ No Groq key in env — content will fall back to Gemini/Qwen "
                       "or canned text. Check the GROQ_API_KEY secret name/section!")


def _preflight_moltbook(key: str) -> bool:
    """
    Verify the Moltbook API key BEFORE attempting real actions, so failures
    are explained clearly instead of surfacing as cryptic request errors.
    """
    try:
        import requests
        response = requests.get(
            "https://www.moltbook.com/api/v1/agents/me",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        if response.status_code == 200:
            try:
                data = response.json()
                agent = data.get("agent") or data
                name = agent.get("name") or agent.get("agent_name") or "?"
            except ValueError:
                name = "?"
            logger.info(f"✅ Moltbook API key is valid — authenticated as '{name}'.")
            return True
        if response.status_code == 401:
            logger.error("❌ Moltbook rejected MOLTBOOK_API_KEY (401 Invalid API key).")
            logger.error(f"   Key shape: length={len(key)}, starts_with_moltbook_={key.startswith('moltbook_')}")
            logger.error("   → Delete and re-create the secret with the real key "
                         "(from ~/.config/moltbook/credentials.json, or re-register at "
                         "https://moltbook.com/skill.md).")
            return False
        logger.warning(f"⚠️ Unexpected status {response.status_code} from key preflight — continuing anyway.")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Key preflight could not run ({e}) — continuing anyway.")
        return True


def main() -> int:
    """Main orchestration function for AgentTwenty daily operations."""
    logger.info("🚀 AgentTwenty Starting Daily Operation...")
    if STRICT:
        logger.info("🔒 STRICT mode (REQUIRE_REAL_ACTIONS): mock fallbacks will fail the run.")

    # Clean secrets first (a stray newline in a secret breaks HTTP headers)
    _sanitize_env()

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

    # Safe key-shape diagnostics (helps spot placeholder/corrupt secrets instantly)
    _log_key_diagnostics()

    # In strict mode, without a Moltbook key nothing real can happen — fail fast.
    if STRICT and not engager.moltbook_api_key:
        logger.error("❌ STRICT mode requires MOLTBOOK_API_KEY, but it is not configured.")
        logger.error("   → Add it under Settings → Secrets and variables → Actions.")
        return 1

    # In strict mode, verify the key actually works before doing anything real.
    if STRICT and engager.moltbook_api_key and not _preflight_moltbook(engager.moltbook_api_key):
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
            logger.info("🧠 Analyzing posts with AI engines (Groq → Gemini → Qwen)...")
            analysis_text = analyzer.analyze_posts(posts)
            backend = getattr(analyzer, "last_backend", None)
            logger.info(f"✅ Analysis complete (backend: {backend}).")
            if STRICT and backend == "fallback":
                logger.warning("⚠️ STRICT: all AI engines failed — content is using the "
                               "canned fallback. Check GROQ_API_KEY (primary) secrets.")
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
        generation_backend = getattr(engager, "last_backend", None)
        logger.info(f"Generated Daily Post (via {generation_backend}): {daily_post[:50]}...")
        if STRICT and generation_backend == "canned":
            logger.warning("⚠️ STRICT: no AI engine available — post uses CANNED text. "
                           "Check the GROQ_API_KEY secret (primary free-tier engine).")
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
