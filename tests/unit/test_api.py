import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Retrieve global mock from conftest
import boto3
mock_table = boto3.resource("dynamodb").Table("NewsArticles")

# Add backend/api to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backend", "api"))

from fastapi.testclient import TestClient
from main import app, verify_api_key

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_get_categories():
    mock_table.query.return_value = {"Count": 5}
    
    response = client.get("/api/categories")
    assert response.status_code == 200
    categories = response.json()
    assert len(categories) == 5
    assert categories[0]["name"] == "AI"
    assert categories[0]["count"] == 5

def test_get_news_all():
    mock_table.query.return_value = {
        "Items": [
            {
                "url_hash": "hash1",
                "title": "AI Breakthrough",
                "description": "A major AI discovery has been made.",
                "url": "https://example.com/ai",
                "source": "TechNews",
                "category": "AI",
                "published_at": "2026-08-11T10:00:00Z",
                "score": 120,
                "created_at": "2026-08-11T10:05:00Z"
            },
            {
                "url_hash": "hash2",
                "title": "Stock Market Rises",
                "description": "Tech stocks lead market rebound.",
                "url": "https://example.com/biz",
                "source": "BizNews",
                "category": "Business",
                "published_at": "2026-08-11T09:00:00Z",
                "score": 105,
                "created_at": "2026-08-11T09:05:00Z"
            }
        ]
    }
    
    response = client.get("/api/news")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["articles"]) == 2
    assert data["articles"][0]["title"] == "AI Breakthrough"
    assert data["articles"][0]["score"] == 120

def test_get_news_filtered_and_search():
    mock_table.query.return_value = {
        "Items": [
            {
                "url_hash": "hash1",
                "title": "AI Breakthrough in NLP",
                "description": "Language models show human-like logic.",
                "url": "https://example.com/ai",
                "source": "TechNews",
                "category": "AI",
                "published_at": "2026-08-11T10:00:00Z",
                "score": 115,
                "created_at": "2026-08-11T10:05:00Z"
            }
        ]
    }
    
    response = client.get("/api/news?category=AI&search=NLP")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert "NLP" in data["articles"][0]["title"]
    
    response = client.get("/api/news?category=AI&search=Sports")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0

def test_trigger_fetch_unauthorized():
    response = client.post("/api/fetch")
    assert response.status_code == 401

def test_trigger_fetch_authorized():
    with patch("main.ADMIN_API_KEY", "test-admin-key"), \
         patch("main.FETCHER_LAMBDA_NAME", "FetcherFunction"), \
         patch("main.boto3.client") as mock_lambda_client:
         
        response = client.post("/api/fetch", headers={"x-api-key": "test-admin-key"})
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        
        mock_lambda_client.return_value.invoke.assert_called_once()
