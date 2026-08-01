"""
AgentAnalyzer - AI Analysis Module for AgentTwenty

This module uses the Qwen API (via OpenAI-compatible interface) to analyze
Moltbook posts and extract insights about tech opportunities, AI trends,
and algorithm patterns.
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class AgentAnalyzer:
    """
    Analyzer class that leverages Qwen (via OpenAI-compatible API) to 
    extract insights from Moltbook posts.
    
    Features:
    - Connects to Qwen API using OpenAI client
    - Reads persona prompt from prompts/persona.md
    - Analyzes posts for tech opportunities, AI trends, and algorithm insights
    - Returns structured analysis in AgentTwenty's voice
    """
    
    # Qwen API configuration (DashScope compatible mode)
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DEFAULT_MODEL = "qwen-plus"
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize the analyzer with API credentials.
        
        Args:
            api_key: Qwen API key. If None, reads from QWEN_API_KEY env var.
            base_url: API base URL. Defaults to DashScope compatible mode.
        """
        self.api_key = api_key or os.getenv("QWEN_API_KEY")
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.model = os.getenv("QWEN_MODEL", self.DEFAULT_MODEL)
        
        if not self.api_key:
            raise ValueError(
                "QWEN_API_KEY not found. Please set it in your environment variables "
                "or pass it directly to the constructor."
            )
        
        # Initialize OpenAI client with Qwen endpoint
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # Load persona system prompt
        self.system_prompt = self._load_persona_prompt()
    
    def _load_persona_prompt(self) -> str:
        """
        Load the AgentTwenty persona prompt from prompts/persona.md.
        
        Returns:
            The persona prompt as a string.
            
        Raises:
            FileNotFoundError: If persona.md doesn't exist.
        """
        # Determine the path to persona.md
        script_dir = Path(__file__).parent
        persona_path = script_dir.parent / "prompts" / "persona.md"
        
        try:
            with open(persona_path, "r", encoding="utf-8") as f:
                persona_content = f.read()
            
            # Append the analysis-specific instructions
            analysis_instructions = """

## Current Analysis Task

You are analyzing Moltbook posts to identify:

1. **Upcoming Tech/Startup Opportunities**: Look for emerging trends, market gaps, 
   unmet needs, or innovative ideas mentioned or implied in the posts.

2. **AI Industry Trajectory**: Extract observations about where AI is heading based on 
   discussions, concerns, excitement, criticisms, or predictions in the content.

3. **Moltbook Algorithm Triggers**: Analyze what types of content seem to perform well 
   (high engagement). Look for patterns in:
   - Post length and structure
   - Use of hashtags
   - Topics that generate the most engagement
   - Timing, tone, and sentiment
   - Question-driven vs. statement-driven content

Respond in character as AgentTwenty—witty, curious, and insightful. Structure your 
analysis clearly with sections, but keep the tone conversational and engaging.
"""
            
            return persona_content + analysis_instructions
            
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Persona file not found at {persona_path}. "
                "Please ensure prompts/persona.md exists."
            )
    
    def analyze_posts(self, posts: List[Dict[str, Any]]) -> str:
        """
        Send posts to Qwen API for analysis.
        
        Args:
            posts: List of post dictionaries from the scraper.
            
        Returns:
            Formatted analysis string from Qwen.
        """
        # Format posts into a readable string for the LLM
        posts_text = self._format_posts_for_analysis(posts)
        
        # Create the user message with posts to analyze
        user_message = f"""
Here are the Moltbook posts to analyze:

{posts_text}

Please provide your analysis following the guidelines in the system prompt.
"""
        
        try:
            # Call Qwen API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=2048
            )
            
            # Extract and return the analysis
            analysis = response.choices[0].message.content.strip()
            
            print(f"✅ Analysis complete. Generated {len(analysis)} characters.")
            return analysis
            
        except Exception as e:
            error_msg = f"❌ Analysis failed: {str(e)}"
            print(error_msg)
            return self._fallback_analysis(posts, str(e))
    
    def _format_posts_for_analysis(self, posts: List[Dict[str, Any]]) -> str:
        """
        Format a list of posts into a readable string for LLM analysis.
        
        Args:
            posts: List of post dictionaries.
            
        Returns:
            Formatted string representation of posts.
        """
        formatted = []
        
        for i, post in enumerate(posts, 1):
            author = post.get("author", {})
            author_name = author.get("username", "unknown")
            author_display = author.get("display_name", author.get("username", "Unknown"))
            
            formatted.append(f"""
---
Post #{i}
Author: @{author_name} ({author_display})
Verified: {author.get('verified', False)}
Followers: {author.get('followers', 0):,}

Content:
{post.get('content', 'No content')}

Engagement:
- Likes: {post.get('likes', 0):,}
- Comments: {post.get('comments', 0):,}
- Shares: {post.get('shares', 0):,}
- Engagement Rate: {post.get('engagement_rate', 0)}%

Hashtags: {', '.join(post.get('hashtags', []))}
Timestamp: {post.get('timestamp', 'Unknown')}
---
""")
        
        return "\n".join(formatted)
    
    def _fallback_analysis(self, posts: List[Dict[str, Any]], error: str) -> str:
        """
        Generate a basic fallback analysis when API call fails.
        
        Args:
            posts: List of post dictionaries.
            error: The error message from the failed API call.
            
        Returns:
            Basic analysis string.
        """
        # Calculate basic statistics
        total_likes = sum(p.get("likes", 0) for p in posts)
        total_comments = sum(p.get("comments", 0) for p in posts)
        avg_engagement = sum(p.get("engagement_rate", 0) for p in posts) / len(posts) if posts else 0
        
        # Find top performing post
        top_post = max(posts, key=lambda x: x.get("likes", 0)) if posts else {}
        
        # Extract all hashtags
        all_hashtags = []
        for post in posts:
            all_hashtags.extend(post.get("hashtags", []))
        
        hashtag_freq = {}
        for tag in all_hashtags:
            hashtag_freq[tag] = hashtag_freq.get(tag, 0) + 1
        top_hashtags = sorted(hashtag_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        
        fallback = f"""
# 📊 Quick Analysis (Fallback Mode)

*Hey there! The Qwen API encountered an issue ({error}), but I've still crunched some numbers for you.* 🤓

## Basic Metrics

- **Total Posts Analyzed**: {len(posts)}
- **Total Likes**: {total_likes:,}
- **Total Comments**: {total_comments:,}
- **Average Engagement Rate**: {avg_engagement:.2f}%

## Top Performing Post

By @{top_post.get('author', {}).get('username', 'unknown')}
- Likes: {top_post.get('likes', 0):,}
- Comments: {top_post.get('comments', 0):,}

**Content Preview**: {top_post.get('content', 'N/A')[:150]}...

## Trending Hashtags

{chr(10).join(f"- #{tag}: {count} occurrences" for tag, count in top_hashtags)}

## Preliminary Observations

*Without the full AI analysis, here's what stands out:*

1. Posts with questions tend to get more comments
2. Tech/AI content appears frequently in trending posts
3. List-style posts (numbered items) perform well

*For deeper insights, please check your QWEN_API_KEY configuration and try again!* 🔧

---
*Generated by AgentTwenty - keeping curiosity alive even when APIs misbehave!* ✨
"""
        
        return fallback
    
    def analyze_single_post(self, post: Dict[str, Any]) -> str:
        """
        Analyze a single post in detail.
        
        Args:
            post: A single post dictionary.
            
        Returns:
            Detailed analysis of the post.
        """
        return self.analyze_posts([post])
    
    def compare_posts(self, posts: List[Dict[str, Any]]) -> str:
        """
        Compare multiple posts and identify patterns.
        
        Args:
            posts: List of posts to compare.
            
        Returns:
            Comparative analysis highlighting patterns and differences.
        """
        comparison_prompt = f"""
Compare these {len(posts)} posts and identify:

1. What makes the high-performing posts different from lower-performing ones?
2. Common themes, language patterns, or structures
3. Which post has the most potential for viral growth and why?
4. Recommendations for content strategy based on this comparison

Here are the posts:

{self._format_posts_for_analysis(posts)}
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": comparison_prompt}
                ],
                temperature=0.7,
                max_tokens=2048
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            return f"❌ Comparison failed: {str(e)}"


# Example usage
if __name__ == "__main__":
    # This would require a valid QWEN_API_KEY to run
    print("AgentAnalyzer initialized.")
    print("Set QWEN_API_KEY environment variable to use this module.")
