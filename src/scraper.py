"""
MoltbookScraper - Data Ingestion Module for AgentTwenty

This module handles fetching posts from Moltbook, with fallback to mock data
when API keys are unavailable or the API is unreachable.
"""

import os
import json
import random
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
    
    # Placeholder API endpoint (to be replaced with actual Moltbook API)
    API_BASE_URL = "https://api.moltbook.com/v1"
    API_ENDPOINT = f"{API_BASE_URL}/posts/trending"
    
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
        
        return mock_posts
    
    def fetch_trending_posts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch trending posts from Moltbook API.
        
        Falls back to mock data if:
        - API key is missing
        - API request fails
        - Response is invalid
        
        Args:
            limit: Maximum number of posts to fetch.
            
        Returns:
            List of post dictionaries.
        """
        # Check if API key is available
        if not self.api_key:
            print("⚠️  MOLTBOOK_API_KEY not found. Using mock data.")
            return self.mock_data()[:limit]
        
        try:
            # Attempt to fetch from API
            params = {"limit": limit, "sort": "trending"}
            
            response = self.session.get(
                self.API_ENDPOINT,
                params=params,
                timeout=10
            )
            
            # Raise exception for HTTP errors
            response.raise_for_status()
            
            data = response.json()
            
            # Extract posts from response (adjust based on actual API structure)
            posts = data.get("posts", data.get("data", []))
            
            if not posts:
                print("⚠️  No posts returned from API. Using mock data.")
                return self.mock_data()[:limit]
            
            print(f"✅ Successfully fetched {len(posts)} posts from Moltbook API")
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
            endpoint = f"{self.API_BASE_URL}/posts/search"
            params = {"q": query, "limit": limit}
            
            response = self.session.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            posts = data.get("posts", data.get("data", []))
            
            return posts if posts else self.mock_data()[:limit]
            
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
