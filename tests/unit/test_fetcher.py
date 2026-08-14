import sys
import os
import pytest

# Add backend/fetcher to python path so we can import lambda_function
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backend", "fetcher"))

from lambda_function import classify_category, calculate_score, parse_rss_date

def test_classify_category_ai():
    title = "OpenAI launches GPT-5 model"
    desc = "The new GPT-5 model shows incredible reasoning capabilities"
    assert classify_category(title, desc) == "AI"
    
    title_2 = "Machine Learning algorithms improve predictions"
    assert classify_category(title_2, "") == "AI"

def test_classify_category_technology():
    title = "Apple announces new iPhone 18 specifications"
    desc = "New phone features micro-LED screen technology"
    assert classify_category(title, desc) == "Technology"
    
    title_2 = "Cybersecurity flaw patched by Microsoft"
    assert classify_category(title_2, "") == "Technology"

def test_classify_category_business():
    title = "Stocks tumble as inflation fears grow"
    desc = "The Federal Reserve warns of higher interest rates"
    assert classify_category(title, desc) == "Business"
    
    title_2 = "Startup raises 50 million in Series A funding"
    assert classify_category(title_2, "") == "Business"

def test_classify_category_sports():
    title = "Real Madrid wins Champions League final"
    desc = "An incredible goal in the 90th minute seals victory"
    assert classify_category(title, desc) == "Sports"
    
    title_2 = "NBA player signs historic contract extension"
    assert classify_category(title_2, "") == "Sports"

def test_classify_category_world():
    title = "Major floods cause disruptions in central Europe"
    desc = "Emergency services deployed to assist citizens"
    assert classify_category(title, desc) == "World"

def test_calculate_score_breaking():
    article_breaking = {
        "title": "Breaking news: Major scientific breakthrough",
        "description": "Scientists announce a revolutionary discovery",
        "published_at": "2026-08-11T09:00:00Z"
    }
    article_normal = {
        "title": "A standard article title",
        "description": "Nothing major happened in this standard article",
        "published_at": "2026-08-11T09:00:00Z"
    }
    
    assert calculate_score(article_breaking) > calculate_score(article_normal)

def test_parse_rss_date():
    date_gmt = "Mon, 10 Aug 2026 11:10:20 GMT"
    parsed = parse_rss_date(date_gmt)
    assert parsed.endswith("Z")
    assert "2026-08-10T11:10:20" in parsed
