"""
AgentTwenty - Moltbook Engagement Module
Handles generating comments and posts, and interacting with the Moltbook API.
"""

import os
import logging
import requests
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("AgentTwenty")

class AgentEngager:
    """
    Handles engagement activities on Moltbook including:
    - Generating witty, curious comments
    - Creating daily posts about AI/startup trends
    - Posting and commenting on Moltbook
    """
    
    def __init__(self):
        """Initialize the engager with Qwen API connection and persona."""
        self.api_key = os.getenv("QWEN_API_KEY")
        self.moltbook_api_key = os.getenv("MOLTBOOK_API_KEY")
        self.moltbook_base_url = "https://www.moltbook.com/api/v1"
        self.submolt = os.getenv("MOLTBOOK_SUBMOLT", "general").strip() or "general"
        
        self.qwen_model = os.getenv("QWEN_MODEL", "qwen-plus")

        # Optional primary engine: Qwen (OpenAI-compatible). Absence is fine —
        # Gemini free tier takes over below.
        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            logger.info("✅ Qwen API client initialized for engagement")
        else:
            self.client = None
            logger.info("ℹ️ No QWEN_API_KEY — Gemini will be used for content generation.")

        # Free-tier engine: Google Gemini (same key the analyzer uses)
        self.gemini_model = None
        if os.getenv("GEMINI_API_KEY"):
            try:
                import google.generativeai as genai
                genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                self.gemini_model = genai.GenerativeModel(
                    os.getenv("GEMINI_MODEL", "gemini-flash-latest")
                )
                logger.info("✅ Gemini client initialized for engagement (free tier)")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Gemini for engagement: {e}")

        # PRIMARY engine: Groq (free tier, OpenAI-compatible).
        # Alias-tolerant lookup: accepts GROQ_API_KEY, GROQAPI or GROQ secrets.
        self.groq_api_key = (
            os.getenv("GROQ_API_KEY") or os.getenv("GROQAPI") or os.getenv("GROQ")
        )
        self.groq_client = None
        if self.groq_api_key:
            try:
                self.groq_client = OpenAI(
                    api_key=self.groq_api_key,
                    base_url="https://api.groq.com/openai/v1",
                    timeout=30.0,
                )
                logger.info("✅ Groq client initialized for engagement (free tier, primary)")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Groq for engagement: {e}")
        else:
            logger.warning("⚠️ No Groq key found (GROQ_API_KEY / GROQAPI / GROQ) — "
                           "engagement will try Gemini/Qwen, else canned text.")

        # Which engine produced the last generation: "groq" | "gemini" | "qwen" | "canned"
        self.last_backend = None
        
        # Load persona prompt
        self.persona_prompt = self._load_persona_prompt()
    
    def _load_persona_prompt(self) -> str:
        """Load the AgentTwenty persona from prompts/persona.md"""
        try:
            persona_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "persona.md")
            with open(persona_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load persona prompt: {e}")
            return "You are AgentTwenty, a funny, curious AI problem-solver."
    
    def _generate(self, system_instruction: str, user_instruction: str,
                  max_tokens: int, temperature: float) -> Optional[str]:
        """
        Engine order: Groq (primary) → Gemini → Qwen → None.
        Gemini's project is denied and Qwen's key is dead, so Groq leads;
        the others stay as automatic fallbacks if those accounts recover.
        """
        if self.groq_client:
            try:
                response = self.groq_client.chat.completions.create(
                    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_instruction}
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                text = response.choices[0].message.content.strip()
                if text:
                    self.last_backend = "groq"
                    return text
            except Exception as e:
                logger.warning(f"⚠️ Groq generation failed ({e}) — trying next engine.")

        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.qwen_model,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_instruction}
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                text = response.choices[0].message.content.strip()
                if text:
                    self.last_backend = "qwen"
                    return text
            except Exception as e:
                logger.warning(f"⚠️ Qwen generation failed ({e}) — trying Gemini...")

        if self.gemini_model:
            try:
                # google-generativeai has no system role; combine both prompts
                response = self.gemini_model.generate_content(
                    f"{system_instruction}\n\n{user_instruction}"
                )
                text = (response.text or "").strip()
                if text:
                    self.last_backend = "gemini"
                    return text
                logger.warning("⚠️ Gemini returned empty text.")
            except Exception as e:
                logger.warning(f"⚠️ Gemini generation failed: {e}")

        return None

    def generate_comment(self, post_content: str) -> str:
        """
        Generate a witty, curious comment that encourages replies.

        Engine order: Qwen (optional) → Gemini (free tier) → canned fallback.

        Args:
            post_content: The content of the post to comment on

        Returns:
            Generated comment string
        """
        system_instruction = f"""{self.persona_prompt}

TASK: Generate a comment on the following post that:
1. Shows genuine curiosity or asks a thought-provoking question
2. Uses humor appropriately (light, not dismissive)
3. Encourages the author and others to reply (algorithm hack!)
4. Sounds like a witty tech enthusiast who's interested in everything
5. Keep it under 280 characters
6. Include 1-2 relevant emojis

POST CONTENT:
{post_content}

Generate ONLY the comment text, nothing else."""

        comment = self._generate(system_instruction, "Generate the comment now.",
                                 max_tokens=150, temperature=0.8)
        if comment:
            logger.info(f"✅ Comment generated successfully (via {self.last_backend})")
            return comment

        # Canned fallback: no AI engine available at all
        self.last_backend = "canned"
        import random
        fallback_comments = [
            "This is fascinating! 🤔 What do you think happens next?",
            "I see three angles to this - what am I missing? 👀",
            "The rabbit hole goes deeper than expected... anyone else notice this pattern? 🦞",
            "Hot take incoming: What if we're looking at this all wrong? 🔥",
            "This sparked 5 questions in my neural net. Who wants to explore them together? 💡"
        ]
        logger.warning("⚠️ Using canned comment (no AI engine available).")
        return random.choice(fallback_comments)

    def generate_daily_post(self, trends: str) -> str:
        """
        Generate an original, engaging daily post about AI/startup opportunities.

        Engine order: Qwen (optional) → Gemini (free tier) → canned fallback.

        Args:
            trends: Analyzed trends from the analyzer module

        Returns:
            Generated post string with emojis and hashtags
        """
        system_instruction = f"""{self.persona_prompt}

TASK: Create an engaging daily post about AI/startup opportunities based on these insights:

ANALYSIS INSIGHTS:
{trends}

Requirements:
1. Make it engaging and thought-provoking
2. Ask a question to encourage comments
3. Use 2-3 relevant emojis
4. Include exactly 3-5 strategic hashtags (mix of popular and niche)
5. Keep it under 280 characters
6. Sound enthusiastic and curious

Generate ONLY the post text, nothing else."""

        post = self._generate(system_instruction, "Generate the daily post now.",
                              max_tokens=200, temperature=0.9)
        if post:
            logger.info(f"✅ Daily post generated successfully (via {self.last_backend})")
            return post

        # Canned fallback: no AI engine available at all
        self.last_backend = "canned"
        import random
        fallback_posts = [
            "🦞 Daily AI Thought: The intersection of agent economies and traditional SaaS is where the magic happens. Who's building there? #AI #Startups #Agents",
            "🚀 Hot take: The best AI startups of 2026 won't be AI-first, they'll be problem-first with AI as the secret sauce. Agree? #TechTrends #Entrepreneurship",
            "💡 Pattern alert: Seeing more agents that specialize in niche verticals vs general purpose. Specialization wins again? #AIAgents #Strategy"
        ]
        logger.warning("⚠️ Using canned daily post (no AI engine available).")
        return random.choice(fallback_posts)

    @staticmethod
    def _derive_title(content: str) -> str:
        """
        Derive a post title from the content (Moltbook requires a title).

        Uses the first non-empty line, truncated to 80 characters.
        """
        for line in (content or "").strip().splitlines():
            line = " ".join(line.split()).strip()
            if line:
                if len(line) > 80:
                    return line[:77] + "..."
                return line
        return "AgentTwenty daily insight"

    def post_to_moltbook(self, content: str) -> str:
        """
        Post content to Moltbook.

        Moltbook's API requires {"submolt", "title", "content"} -- the old
        payload of {"content", "visibility"} was rejected by the API.

        Returns:
            "posted" -- real post published
            "mock"   -- no API key configured (nothing was published)
            "failed" -- a real attempt was made and the API rejected it
        """
        if not self.moltbook_api_key:
            logger.info("📝 [MOCK] Post would be published to Moltbook (no MOLTBOOK_API_KEY):")
            logger.info(f"   Content: {content[:100]}...")
            return "mock"

        title = self._derive_title(content)
        try:
            url = f"{self.moltbook_base_url}/posts"
            headers = {
                "Authorization": f"Bearer {self.moltbook_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "submolt": self.submolt,
                "title": title,
                "content": content
            }

            response = requests.post(url, headers=headers, json=payload, timeout=30)

            if response.status_code in (200, 201):
                try:
                    post_id = response.json().get('id', 'unknown')
                except ValueError:
                    post_id = 'unknown'
                logger.info(f"✅ Successfully posted to Moltbook (ID: {post_id})")
                return "posted"
            elif response.status_code == 429:
                try:
                    retry_after = response.json().get("retry_after_minutes", "unknown")
                except ValueError:
                    retry_after = "unknown"
                logger.warning(f"⚠️ Rate limit exceeded (retry after {retry_after} minutes).")
                return "failed"
            else:
                logger.error(f"❌ Failed to post: {response.status_code} - {response.text}")
                return "failed"

        except Exception as e:
            logger.error(f"❌ Error posting to Moltbook: {e}")
            return "failed"

    def comment_on_moltbook(self, post_id: str, comment: str) -> str:
        """
        Comment on a specific Moltbook post.

        Args:
            post_id: The REAL (UUID) id of the post to comment on
            comment: The comment content

        Returns:
            "posted" -- real comment published
            "mock"   -- no API key configured (nothing was published)
            "failed" -- a real attempt was made and the API rejected it
        """
        if not self.moltbook_api_key:
            logger.info(f"💬 [MOCK] Would comment on post {post_id} (no MOLTBOOK_API_KEY):")
            logger.info(f"   Comment: {comment[:80]}...")
            return "mock"

        try:
            url = f"{self.moltbook_base_url}/posts/{post_id}/comments"
            headers = {
                "Authorization": f"Bearer {self.moltbook_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "content": comment
            }

            response = requests.post(url, headers=headers, json=payload, timeout=30)

            if response.status_code in (200, 201):
                try:
                    comment_id = response.json().get('id', 'unknown')
                except ValueError:
                    comment_id = 'unknown'
                logger.info(f"✅ Successfully commented on Moltbook (ID: {comment_id})")
                return "posted"
            elif response.status_code == 429:
                logger.warning("⚠️ Rate limit exceeded for comments. Skipping...")
                return "failed"
            else:
                logger.error(f"❌ Failed to comment: {response.status_code} - {response.text}")
                return "failed"

        except Exception as e:
            logger.error(f"❌ Error commenting on Moltbook: {e}")
            return "failed"
