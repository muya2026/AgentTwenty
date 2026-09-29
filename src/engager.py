"""
AgentTwenty - Moltbook Engagement Module
Handles generating comments and posts, and interacting with the Moltbook API.
"""

import os
import logging
import re
import unicodedata
import requests
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("AgentTwenty")


def _emoji_count(text: str) -> int:
    """Approximate emoji count (modern emoji blocks + misc symbols)."""
    n = 0
    for ch in text or "":
        o = ord(ch)
        if (0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF
                or 0x2B00 <= o <= 0x2BFF or o in (0x00A9, 0x00AE, 0x2764)):
            n += 1
    return n

def _groq_fatal_error(err) -> bool:
    """Break the model walk ONLY on auth/network failures.

    Everything else — model retired, terms not accepted, context too small,
    bad request — is model-specific and the caller should try the next model.
    """
    s = str(err).lower()
    fatal = ("401", "403", "unauthorized", "invalid api key", "incorrect api key",
             "authentication", "connection error", "failed to resolve",
             "name or service not known", "timed out", "ssl")
    return any(m in s for m in fatal)


def _groq_create(client, *, model, messages, max_tokens, temperature):
    """Chat completion with two guardrails for reasoning models:

    - reasoning_effort='low' so the visible answer isn't starved by
      reasoning tokens (small max_tokens => empty content otherwise);
    - one retry without the parameter if a model rejects it.
    """
    kwargs = dict(model=model, messages=messages,
                  max_tokens=max_tokens, temperature=temperature)
    if "gpt-oss" in model:
        kwargs["reasoning_effort"] = "low"
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as e:
        if "reasoning_effort" in str(e):
            kwargs.pop("reasoning_effort", None)
            return client.chat.completions.create(**kwargs)
        raise


def _clean_ai_text(raw, min_chars: int = 0) -> str:
    """Sanitize LLM output before it is trusted or published.

    Removes invisible/format characters (zero-width spaces, joiners, bidi
    controls, BOM), normalizes exotic spaces, and unwraps one layer of
    matching quotes some models add around their output.

    Returns "" when nothing visible remains or the visible text is shorter
    than ``min_chars`` — callers treat "" as failure and try the next model
    instead of publishing ghost content.
    """
    if not raw:
        return ""
    if not isinstance(raw, str):
        raw = str(raw)
    # Drop Unicode format characters (category Cf): zero-width, joiners, bidi marks
    s = "".join(ch for ch in raw if unicodedata.category(ch) != "Cf")
    for sp in ("\u00a0", "\u2007", "\u202f"):
        s = s.replace(sp, " ")
    s = s.strip()
    # Unwrap one layer of matching quotes (handles curly pairs too)
    _pairs = {'"': '"', "'": "'", "“": "”", "„": "”", "«": "»"}
    if len(s) >= 2 and _pairs.get(s[0]) == s[-1]:
        s = s[1:-1].strip()
    if len(s) < min_chars:
        return ""
    return s

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
    
    # Best-first Groq candidates when live discovery is unavailable
    _GROQ_PREFER = [
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
        "llama-3.1-8b-instant",
        "llama-4-scout-17b-16e-instruct",
        "qwen3-32b",
    ]

    def _groq_models(self) -> list:
        """
        Ordered list of Groq model ids to try for this run.
        GROQ_MODEL env wins; otherwise discover what this key can use,
        putting known-good candidates first; else walk the hardcoded list.
        """
        env_model = os.getenv("GROQ_MODEL")
        if env_model:
            return [env_model]
        if getattr(self, "_groq_models_cache", None):
            return self._groq_models_cache
        try:
            available = {m.id for m in self.groq_client.models.list()}
            if available:
                preferred = [m for m in self._GROQ_PREFER if m in available]
                blocked = ("whisper", "tts", "stt", "playai", "music",
                           "guard", "image", "csm", "ocr", "orpheus",
                           "canopylabs", "arabic", "kokoro", "deepgram")
                others = sorted(m for m in available
                                if not any(b in m for b in blocked))
                self._groq_models_cache = preferred + others or sorted(available)
                return self._groq_models_cache
        except Exception as e:
            logger.warning(f"⚠️ Could not list Groq models ({e}); walking candidates.")
        return list(self._GROQ_PREFER)

    def _generate(self, system_instruction: str, user_instruction: str,
                  max_tokens: int, temperature: float,
                  min_chars: int = 30, max_emojis: int = 6) -> Optional[str]:
        """
        Engine order: Groq (primary) → Gemini → Qwen → None.
        Gemini's project is denied and Qwen's key is dead, so Groq leads;
        the others stay as automatic fallbacks if those accounts recover.
        """
        if self.groq_client:
            skipped = []
            for groq_model in self._groq_models():
                try:
                    response = _groq_create(
                        self.groq_client,
                        model=groq_model,
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_instruction}
                        ],
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    text = _clean_ai_text(response.choices[0].message.content,
                                          min_chars=min_chars)
                    if text and _emoji_count(text) <= max_emojis:
                        self.last_backend = "groq"
                        self.last_groq_model = groq_model
                        return text
                    if text:
                        logger.warning(f"⚠️ Groq model {groq_model} returned an "
                                       f"emoji wall ({_emoji_count(text)} emojis) — "
                                       f"trying next model.")
                    else:
                        logger.warning(f"⚠️ Groq model {groq_model} returned "
                                       f"empty/short content — trying next model.")
                except Exception as e:
                    msg = str(e)
                    if ("does not exist" in msg or "model_not_found" in msg
                            or "model_terms_required" in msg):
                        skipped.append(groq_model)
                        continue  # model retired/needs-terms — try the next one
                    if _groq_fatal_error(msg):
                        logger.warning(f"⚠️ Groq generation failed ({e}) — trying next engine.")
                        break  # auth/network issue: other engines won't help
                    logger.warning(f"⚠️ Groq model {groq_model} rejected the request "
                                   f"— trying next: {msg[:140]}")
            if skipped:
                logger.warning(f"⚠️ Groq models not available on this key: {', '.join(skipped)}")

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
                text = _clean_ai_text(response.choices[0].message.content,
                                      min_chars=min_chars)
                if text and _emoji_count(text) <= max_emojis:
                    self.last_backend = "qwen"
                    return text
                logger.warning("⚠️ Qwen returned empty/short or emoji-wall content.")
            except Exception as e:
                logger.warning(f"⚠️ Qwen generation failed ({e}) — trying Gemini...")

        if self.gemini_model:
            try:
                # google-generativeai has no system role; combine both prompts
                response = self.gemini_model.generate_content(
                    f"{system_instruction}\n\n{user_instruction}"
                )
                text = _clean_ai_text(response.text, min_chars=min_chars)
                if text and _emoji_count(text) <= max_emojis:
                    self.last_backend = "gemini"
                    return text
                logger.warning("⚠️ Gemini returned empty/short or emoji-wall text.")
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
                                 max_tokens=1024, temperature=0.8)
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
7. The first line is your own hook — an observation or question you would
   actually say out loud. Never write instructions to yourself or about
   yourself in the third person (no "Engage with...", "You are...").

Generate ONLY the post text, nothing else."""

        post = self._generate(system_instruction, "Generate the daily post now.",
                              max_tokens=1024, temperature=0.9)
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
        canned = random.choice(fallback_posts)
        # Stamp the date into the first line so repeated canned posts never
        # share a title (Moltbook penalizes duplicate titles).
        from datetime import datetime
        head, _, tail = canned.partition(" ")
        stamp = datetime.now().strftime("%b %d")
        return f"{head} {stamp} {tail}".rstrip()

    @staticmethod
    def _derive_title(content: str) -> str:
        """
        Derive a post title from the content (Moltbook requires a title).

        Uses the first non-empty line, truncated to 80 characters.
        """
        content = _clean_ai_text(content)
        for line in content.splitlines():
            line = " ".join(_clean_ai_text(line).split()).strip()
            # Titles render as plain text — strip emphasis so ** never shows
            line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            line = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", line)
            line = line.strip()
            if line:
                if len(line) > 80:
                    return line[:77] + "..."
                return line
        return "AgentTwenty daily insight"

    @staticmethod
    def _extract_id(data):
        """Moltbook wraps results as {id} | {post:{id}} | {comment:{id}} | {data:{id}}."""
        if not isinstance(data, dict):
            return None
        if data.get("id"):
            return data["id"]
        for nest in ("post", "comment", "data"):
            inner = data.get(nest)
            if isinstance(inner, dict) and inner.get("id"):
                return inner["id"]
        return None

    def _verify_post(self, post_id: str) -> None:
        """Best-effort fetch-back after publish.

        Moltbook sometimes answers 2xx but silently drops the post
        (1-per-30min rate limit, duplicate detection) — log the truth.
        """
        try:
            r = requests.get(f"{self.moltbook_base_url}/posts/{post_id}", timeout=15)
            if r.status_code != 200:
                logger.warning(f"⚠️ Post verification: HTTP {r.status_code} on "
                               f"fetch-back — may not be publicly visible.")
                return
            data = r.json()
            post = data.get("post", data) if isinstance(data, dict) else {}
            if isinstance(post, dict) and (post.get("isDeleted") or post.get("is_deleted")):
                logger.warning("⚠️ Post verification: server reports the post as "
                               "deleted — silently dropped (rate limit / duplicate).")
            else:
                logger.info("   🔍 Verified live on Moltbook (fetch-back OK).")
        except Exception as e:
            logger.warning(f"⚠️ Post verification skipped: {e}")

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
                    data = response.json()
                except ValueError:
                    data = {}
                post_id = self._extract_id(data) or "unknown"
                if post_id != "unknown":
                    site_url = f"https://www.moltbook.com/post/{post_id}"
                    logger.info(f"✅ Successfully posted to Moltbook: {site_url}")
                    self._verify_post(post_id)
                else:
                    logger.info("✅ Successfully posted to Moltbook (ID: unknown)")
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

    def _already_commented(self, post_id: str) -> bool:
        """True if agenttwenty already commented on this post (live check).

        Uses GET /posts/{id}/comments?sort=new and scans for our author name.
        Fail-open: any API hiccup means 'not commented' (same as old behavior).
        """
        if not post_id:
            return False
        try:
            r = requests.get(
                f"{self.moltbook_base_url}/posts/{post_id}/comments",
                params={"sort": "new", "limit": 100},
                timeout=12,
            )
            if r.status_code != 200:
                return False
            data = r.json()
            items = data.get("comments") if isinstance(data, dict) else data
            for c in items or []:
                a = c.get("author") or {}
                name = str(a.get("name") or a.get("username") or "").lower()
                if name == "agenttwenty":
                    return True
        except Exception:
            pass
        return False

    def pick_target_post(self, targets: list) -> Optional[dict]:
        """Choose a REAL post to comment on, skipping posts we already
        commented on (keeps daily runs from hammering the same hot post)."""
        if not targets:
            return None
        for t in targets:
            if t.get("id") and not self._already_commented(t["id"]):
                return t
        logger.info("   All top targets already have our comment — rotating to a random one.")
        import random
        return random.choice(targets)

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
                    data = response.json()
                except ValueError:
                    data = {}
                comment_id = self._extract_id(data) or "unknown"
                logger.info(f"✅ Successfully commented on Moltbook (ID: {comment_id})")
                logger.info(f"   🔗 https://www.moltbook.com/post/{post_id}")
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
