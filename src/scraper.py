"""
MoltbookScraper - Data Ingestion Module for AgentTwenty

This module handles fetching posts from Moltbook, with fallback to mock data
when API keys are unavailable or the API is unreachable.
"""

import os
import json
import random
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class MoltbookScraper:
    """
    Scraper class for ingesting posts from Moltbook platform.
    
    Features:
    - Fetches trending posts from Moltbook API
    - Falls back to realistic mock data when API is unavailable
    - Handles authentication via environment variables
    """
    
    # Real Moltbook API (verified): https://www.moltbook.com/api/v1
    # NOTE: the old "https://api.moltbook.com/v1" domain does not even resolve in DNS.
    API_BASE_URL = "https://www.moltbook.com/api/v1"
    API_ENDPOINT = f"{API_BASE_URL}/posts"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the scraper with API credentials.
        
        Args:
            api_key: Moltbook API key. If None, reads from MOLTBOOK_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("MOLTBOOK_API_KEY")
        self.session = requests.Session()
        
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            })
    
    def mock_data(self) -> List[Dict[str, Any]]:
        """
        Generate realistic mock posts for testing and development.
        
        Returns:
            List of 3 sample posts in JSON-compatible format.
        """
        base_time = datetime.now()
        
        mock_posts = [
            {
                "id": "post_001",
                "author": {
                    "username": "techvisionary_ai",
                    "display_name": "Alex Chen",
                    "verified": True,
                    "followers": 45200
                },
                "content": "Just shipped our MVP after 6 months of building in stealth. The biggest lesson? Talk to users BEFORE writing code. We pivoted 3 times based on feedback. Now we have 500 beta users and growing 🚀\n\n#startup #mvp #buildinpublic #saas",
                "likes": 1847,
                "comments": 234,
                "shares": 89,
                "timestamp": (base_time - timedelta(hours=2)).isoformat(),
                "hashtags": ["startup", "mvp", "buildinpublic", "saas"],
                "media": [],
                "engagement_rate": 4.8
            },
            {
                "id": "post_002",
                "author": {
                    "username": "ai_researcher_jane",
                    "display_name": "Dr. Jane Morrison",
                    "verified": True,
                    "followers": 128000
                },
                "content": "Hot take: The real AI revolution isn't in LLMs—it's in the infrastructure layer. Vector databases, inference optimization, edge deployment... that's where the next 10x companies will be built.\n\nWho's working on something interesting in this space? Drop your projects below 👇\n\n#ai #infrastructure #vectordb #machinelearning",
                "likes": 3421,
                "comments": 567,
                "shares": 234,
                "timestamp": (base_time - timedelta(hours=5)).isoformat(),
                "hashtags": ["ai", "infrastructure", "vectordb", "machinelearning"],
                "media": [],
                "engagement_rate": 7.2
            },
            {
                "id": "post_003",
                "author": {
                    "username": "founder_stories",
                    "display_name": "Startup Chronicles",
                    "verified": False,
                    "followers": 23400
                },
                "content": "Asked 100 founders what they wish they knew before starting:\n\n1. Co-founder fit > idea quality\n2. Distribution is harder than product\n3. Mental health compounds (good and bad)\n4. Say no to most opportunities\n5. Revenue solves many problems\n\nWhat would you add to this list?\n\n#entrepreneurship #startups #founders #lessons",
                "likes": 892,
                "comments": 156,
                "shares": 67,
                "timestamp": (base_time - timedelta(hours=8)).isoformat(),
                "hashtags": ["entrepreneurship", "startups", "founders", "lessons"],
                "media": [],
                "engagement_rate": 3.9
            }
        ]

        for post in mock_posts:
            post["mock"] = True

        return mock_posts

    @staticmethod
    def _normalize_post(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a real Moltbook API post into the internal shape
        expected by the analyzer/engager modules.

        Real API fields: id, title, content, author{name, isClaimed,
        followerCount}, upvotes, comment_count, created_at, submolt, ...
        Internal shape:  author{username,...}, likes, comments, hashtags, ...
        """
        author = raw.get("author") or {}
        username = author.get("name") or author.get("username") or "unknown"
        content = raw.get("content") or raw.get("title") or ""
        followers = int(author.get("followerCount") or author.get("followers") or 0)
        likes = int(raw.get("upvotes") if raw.get("upvotes") is not None else raw.get("likes", 0) or 0)
        comments = int(raw.get("comment_count") if raw.get("comment_count") is not None else raw.get("comments", 0) or 0)
        hashtags = raw.get("hashtags") or re.findall(r"#(\w+)", content)
        engagement_rate = round(((likes + comments) / followers) * 100, 2) if followers else 0.0

        return {
            "id": raw.get("id"),
            "title": raw.get("title", ""),
            "author": {
                "username": username,
                "display_name": author.get("name") or username,
                "verified": bool(author.get("isClaimed") or author.get("verified")),
                "followers": followers,
            },
            "content": content,
            "likes": likes,
            "comments": comments,
            "shares": int(raw.get("shares", 0) or 0),
            "timestamp": raw.get("created_at") or raw.get("timestamp") or "",
            "hashtags": hashtags,
            "engagement_rate": engagement_rate,
            "submolt": (raw.get("submolt") or {}).get("name") if isinstance(raw.get("submolt"), dict) else raw.get("submolt"),
            "mock": bool(raw.get("mock", False)),
        }

    def fetch_trending_posts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch trending/hot posts from the real Moltbook API.

        The public feed (GET /posts) does not require authentication, so we
        always try the live API first. Falls back to clearly-flagged mock data
        only when the request itself fails.

        Args:
            limit: Maximum number of posts to fetch.

        Returns:
            List of normalized post dictionaries (each carries a "mock" flag).
        """
        if not self.api_key:
            print("ℹ️  MOLTBOOK_API_KEY not found — using the public feed (no auth).")

        try:
            params = {"limit": limit, "sort": "hot"}

            response = self.session.get(
                self.API_ENDPOINT,
                params=params,
                timeout=15
            )

            response.raise_for_status()
            data = response.json()

            raw_posts = data.get("posts", data.get("data", []))

            if not raw_posts:
                print("⚠️  No posts returned from API. Using mock data.")
                return self.mock_data()[:limit]

            posts = [self._normalize_post(p) for p in raw_posts]
            print(f"✅ Successfully fetched {len(posts)} REAL posts from Moltbook API")
            return posts

        except requests.exceptions.RequestException as e:
            print(f"⚠️  API request failed: {str(e)}. Falling back to mock data.")
            return self.mock_data()[:limit]

        except json.JSONDecodeError as e:
            print(f"⚠️  Invalid JSON response: {str(e)}. Using mock data.")
            return self.mock_data()[:limit]

        except Exception as e:
            print(f"⚠️  Unexpected error: {str(e)}. Using mock data.")
            return self.mock_data()[:limit]
    
    def fetch_user_posts(self, username: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fetch posts from a specific user.
        
        Args:
            username: The username to fetch posts from.
            limit: Maximum number of posts to fetch.
            
        Returns:
            List of post dictionaries.
        """
        if not self.api_key:
            print("⚠️  MOLTBOOK_API_KEY not found. Using mock data.")
            return self.mock_data()[:limit]
        
        try:
            endpoint = f"{self.API_BASE_URL}/users/{username}/posts"
            params = {"limit": limit}
            
            response = self.session.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            posts = data.get("posts", data.get("data", []))
            
            return posts if posts else self.mock_data()[:limit]
            
        except Exception as e:
            print(f"⚠️  Failed to fetch user posts: {str(e)}. Using mock data.")
            return self.mock_data()[:limit]
    
    def search_posts(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search posts by keyword or hashtag.
        
        Args:
            query: Search query string.
            limit: Maximum number of posts to fetch.
            
        Returns:
            List of post dictionaries.
        """
        if not self.api_key:
            print("⚠️  MOLTBOOK_API_KEY not found. Using mock data.")
            return self.mock_data()[:limit]
        
        try:
            endpoint = f"{self.API_BASE_URL}/search"
            params = {"q": query, "type": "posts", "limit": limit}

            response = self.session.get(endpoint, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            raw_posts = data.get("posts", data.get("data", data.get("results", [])))

            if not raw_posts:
                return self.mock_data()[:limit]
            return [self._normalize_post(p) for p in raw_posts]
            
        except Exception as e:
            print(f"⚠️  Search failed: {str(e)}. Using mock data.")
            return self.mock_data()[:limit]


# Example usage
if __name__ == "__main__":
    scraper = MoltbookScraper()
    posts = scraper.fetch_trending_posts(limit=3)
    
    print("\n📊 Fetched Posts:")
    print("=" * 60)
    for i, post in enumerate(posts, 1):
        print(f"\n{i}. By @{post['author']['username']}")
        print(f"   Content: {post['content'][:100]}...")
        print(f"   Engagement: {post['likes']} likes, {post['comments']} comments")
        print(f"   Hashtags: {', '.join(post['hashtags'])}")
    print("=" * 60)
