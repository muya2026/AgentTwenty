"""
AgentTwenty - Moltbook Engagement Bot
Main orchestrator script that coordinates scraping, analysis, engagement, and reporting.
"""

import os
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
    exit(1)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AgentTwenty")

def main():
    """Main orchestration function for AgentTwenty daily operations."""
    logger.info("🚀 AgentTwenty Starting Daily Operation...")
    
    # Initialize Components
    scraper = MoltbookScraper()
    analyzer = AgentAnalyzer()
    engager = AgentEngager()
    reporter = Reporter()
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    posts = []
    analysis_text = ""
    
    # Step 1: Scrape Data
    try:
        logger.info("📡 Scraping Moltbook for trending posts...")
        posts = scraper.fetch_trending_posts()
        if not posts:
            logger.warning("No posts retrieved. Using mock data fallback if available.")
        else:
            logger.info(f"✅ Successfully fetched {len(posts)} posts.")
    except Exception as e:
        logger.error(f"❌ Scraping failed: {e}")
        # Continue with empty list or mock data if implemented in scraper fallback

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
        
        # Comment on top post
        if posts:
            top_post_content = posts[0].get('content', '')
            comment = engager.generate_comment(top_post_content)
            logger.info(f"Generated Comment: {comment[:50]}...")
            # Attempt to post comment
            engager.comment_on_moltbook(post_id=posts[0].get('id', 'mock_id'), comment=comment)
        else:
            logger.info("No posts to comment on.")

        # Generate Daily Post
        daily_post = engager.generate_daily_post(analysis_text)
        logger.info(f"Generated Daily Post: {daily_post[:50]}...")
        # Attempt to publish daily post
        engager.post_to_moltbook(daily_post)
        
        logger.info("✅ Engagement actions completed.")
    except Exception as e:
        logger.error(f"❌ Engagement failed: {e}")

    # Step 4: Report
    try:
        logger.info("📝 Generating Markdown report...")
        report_path = reporter.generate_markdown_report(analysis_text, current_date)
        logger.info(f"✅ Report saved to: {report_path}")

        # Send via Telegram
        logger.info("📤 Sending Telegram report...")
        reporter.send_telegram_report(report_path)

        # Send via Email
        logger.info("📧 Sending Email report...")
        reporter.send_email_report(report_path, analysis_text)
        
        logger.info("✅ Reporting cycle complete.")
    except Exception as e:
        logger.error(f"❌ Reporting failed: {e}")

    logger.info("🏁 AgentTwenty Daily Operation Finished.")

if __name__ == "__main__":
    main()
