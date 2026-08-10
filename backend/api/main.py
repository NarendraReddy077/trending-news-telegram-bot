import os
import json
import boto3
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel
from typing import Optional, List
from boto3.dynamodb.conditions import Key

# Initialize FastAPI
app = FastAPI(title="Telegram Trending News API", version="1.0")

# CORS middleware for local testing (CloudFront will bypass CORS in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
)

# AWS Configuration
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "NewsArticles")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
FETCHER_LAMBDA_NAME = os.environ.get("FETCHER_LAMBDA_NAME", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "default-admin-key")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

# Pydantic models for responses
class Article(BaseModel):
    url_hash: str
    title: str
    description: str
    url: str
    source: str
    category: str
    published_at: str
    score: int
    created_at: str

class NewsResponse(BaseModel):
    articles: List[Article]
    total: int
    limit: int
    offset: int

class CategoryInfo(BaseModel):
    name: str
    count: int

# Security dependency for POST /fetch
def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

@app.get("/api/health")
def health():
    return {"status": "healthy", "table": DYNAMODB_TABLE}

@app.get("/api/categories", response_model=List[CategoryInfo])
def get_categories():
    """Retrieve list of categories and counts of news articles from the last 7 days."""
    import datetime
    seven_days_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat() + "Z"
    
    categories = ["AI", "Technology", "Business", "Sports", "World"]
    category_counts = []
    
    for cat in categories:
        try:
            # Query count of items in CategoryIndex
            response = table.query(
                IndexName="CategoryIndex",
                KeyConditionExpression=Key("category").eq(cat) & Key("published_at").gt(seven_days_ago),
                Select="COUNT"
            )
            category_counts.append(CategoryInfo(name=cat, count=response.get("Count", 0)))
        except Exception as e:
            category_counts.append(CategoryInfo(name=cat, count=0))
            
    return category_counts

@app.get("/api/news", response_model=NewsResponse)
def get_news(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search term in title/description"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Retrieve news articles from DynamoDB with sorting, searching, and pagination."""
    import datetime
    
    # Restrict to last 14 days to keep performance fast
    fourteen_days_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=14)).isoformat() + "Z"
    
    items = []
    try:
        if category:
            res = table.query(
                IndexName="CategoryIndex",
                KeyConditionExpression=Key("category").eq(category) & Key("published_at").gt(fourteen_days_ago),
                ScanIndexForward=False, # Latest first
                Limit=150
            )
            items = res.get("Items", [])
        else:
            res = table.query(
                IndexName="GlobalIndex",
                KeyConditionExpression=Key("active").eq("1") & Key("published_at").gt(fourteen_days_ago),
                ScanIndexForward=False, # Latest first
                Limit=150
            )
            items = res.get("Items", [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

    # Sort primarily by score descending (trending news)
    items.sort(key=lambda x: int(x.get("score", 100)), reverse=True)

    # Apply search filter if specified (case insensitive)
    if search:
        search_lower = search.lower()
        items = [
            item for item in items 
            if search_lower in item.get("title", "").lower() 
            or search_lower in item.get("description", "").lower()
        ]
        
    total_count = len(items)
    
    # Apply pagination
    paginated_items = items[offset : offset + limit]
    
    # Map raw DynamoDB items to Pydantic objects
    articles = []
    for item in paginated_items:
        articles.append(Article(
            url_hash=item.get("url_hash", ""),
            title=item.get("title", ""),
            description=item.get("description", ""),
            url=item.get("url", ""),
            source=item.get("source", "Unknown"),
            category=item.get("category", "World"),
            published_at=item.get("published_at", ""),
            score=int(item.get("score", 100)),
            created_at=item.get("created_at", "")
        ))
        
    return NewsResponse(
        articles=articles,
        total=total_count,
        limit=limit,
        offset=offset
    )

@app.post("/api/fetch")
def trigger_fetch(api_key: str = Depends(verify_api_key)):
    """Trigger the news fetcher Lambda function on-demand."""
    if not FETCHER_LAMBDA_NAME:
        raise HTTPException(status_code=500, detail="Fetcher Lambda Name environment variable not set.")
        
    try:
        client = boto3.client("lambda", region_name=AWS_REGION)
        client.invoke(
            FunctionName=FETCHER_LAMBDA_NAME,
            InvocationType="Event",
            Payload=json.dumps({"source": "api_manual_trigger"})
        )
        return {"status": "success", "message": "News fetcher Lambda triggered."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to invoke Lambda: {str(e)}")

# Mangum Handler for AWS Lambda integration
handler = Mangum(app, lifespan="off")
