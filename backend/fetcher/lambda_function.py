import os
import re
import json
import hashlib
import datetime
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import boto3
from boto3.dynamodb.conditions import Key

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# DynamoDB Configuration
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "NewsArticles")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "")

# Default RSS Feeds for Zero-Config Out-of-the-Box Operation
RSS_FEEDS = {
    "AI": "https://news.google.com/rss/search?q=Artificial+Intelligence+OR+AI+OR+ChatGPT+OR+LLM&hl=en-US&gl=US&ceid=US:en",
    "Technology": "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "Sports": "http://feeds.bbci.co.uk/news/sport/rss.xml",
    "World": "http://feeds.bbci.co.uk/news/world/rss.xml"
}

# Simple helper to clean HTML tags from strings
def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def get_secrets():
    """Retrieve secrets from AWS Secrets Manager or Environment variables."""
    secret_name = os.environ.get("SECRETS_NAME", "TelegramNewsBotSecrets")
    
    # Try fetching from environment first (for local testing)
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    news_api_key = os.environ.get("NEWS_API_KEY")
    
    if bot_token and chat_id:
        return bot_token, chat_id, news_api_key
        
    try:
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = client.get_secret_value(SecretId=secret_name)
        secrets = json.loads(response["SecretString"])
        return (
            secrets.get("TELEGRAM_BOT_TOKEN"),
            secrets.get("TELEGRAM_CHAT_ID"),
            secrets.get("NEWS_API_KEY")
        )
    except Exception as e:
        logger.error(f"Error fetching secrets from Secrets Manager: {e}")
        return bot_token, chat_id, news_api_key

def fetch_rss_feed(category, url):
    """Fetch and parse articles from an RSS feed using xml.etree (native, safe fallback)."""
    articles = []
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read()
            
        root = ET.fromstring(html)
        channel = root.find("channel")
        if channel is None:
            return articles
            
        items = channel.findall("item")
        for item in items:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_date_el = item.find("pubDate")
            
            title = title_el.text if title_el is not None else ""
            link = link_el.text if link_el is not None else ""
            desc = desc_el.text if desc_el is not None else ""
            pub_date_raw = pub_date_el.text if pub_date_el is not None else ""
            
            if not title or not link:
                continue
                
            # Parse published date
            published_at = parse_rss_date(pub_date_raw)
            
            # Simple source identification
            source = "Google News" if "google.com" in url else "BBC News"
            if "techcrunch" in url:
                source = "TechCrunch"
                
            articles.append({
                "title": clean_html(title),
                "description": clean_html(desc)[:300],
                "url": link,
                "source": source,
                "category": category,
                "published_at": published_at
            })
    except Exception as e:
        logger.error(f"Error fetching RSS feed {category} ({url}): {e}")
    return articles

def parse_rss_date(date_str):
    """Parse common RSS date formats into ISO 8601 UTC format."""
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    if not date_str:
        return now_iso
    try:
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
            "%d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z"
        ):
            try:
                clean_date = date_str.strip()
                if clean_date.endswith("GMT"):
                    clean_date = clean_date[:-3] + "+0000"
                dt = datetime.datetime.strptime(clean_date, fmt)
                if dt.tzinfo:
                    dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                return dt.isoformat() + "Z"
            except ValueError:
                continue
    except Exception:
        pass
    return now_iso

def fetch_newsapi(api_key):
    """Fetch top headlines from NewsAPI.org."""
    articles = []
    if not api_key:
        return articles
        
    url = f"https://newsapi.org/v2/top-headlines?language=en&pageSize=50&apiKey={api_key}"
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "TelegramNewsBotFetcher/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            
        if data.get("status") != "ok":
            logger.error(f"NewsAPI error response: {data}")
            return articles
            
        for item in data.get("articles", []):
            title = item.get("title")
            link = item.get("url")
            desc = item.get("description") or ""
            source = item.get("source", {}).get("name") or "NewsAPI"
            pub_date = item.get("publishedAt") or (datetime.datetime.utcnow().isoformat() + "Z")
            
            if not title or not link:
                continue
                
            # Classify category dynamically based on keywords in title & description
            category = classify_category(title, desc)
            
            articles.append({
                "title": clean_html(title),
                "description": clean_html(desc)[:300],
                "url": link,
                "source": source,
                "category": category,
                "published_at": pub_date
            })
    except Exception as e:
        logger.error(f"Error fetching from NewsAPI: {e}")
    return articles

def classify_category(title, description):
    """Classify articles into categories based on word-boundary keyword matching."""
    text = f"{title} {description}".lower()
    
    # Keyword classification
    ai_keywords = ["ai", "artificial intelligence", "chatgpt", "openai", "llm", "neural network", "machine learning", "deep learning", "anthropic", "claude", "gemini", "copilot"]
    tech_keywords = ["tech", "technology", "software", "hardware", "apple", "google", "microsoft", "meta", "cybersecurity", "hack", "semiconductor", "nvidia", "silicon valley", "gadget"]
    business_keywords = ["business", "finance", "stocks", "market", "startup", "economy", "inflation", "acquisition", "merger", "crypto", "bitcoin", "dollar", "fed"]
    sports_keywords = ["sports", "football", "basketball", "soccer", "olympics", "nba", "nfl", "tennis", "athlete", "championship", "champions", "league", "cup", "stadium", "match", "tournament"]
    
    def match_keywords(keywords):
        for kw in keywords:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, text):
                return True
        return False

    if match_keywords(ai_keywords):
        return "AI"
    elif match_keywords(tech_keywords):
        return "Technology"
    elif match_keywords(business_keywords):
        return "Business"
    elif match_keywords(sports_keywords):
        return "Sports"
    else:
        return "World"

def calculate_score(article):
    """Rank articles based on keyword prominence and publish recency."""
    score = 100
    title_lower = article["title"].lower()
    desc_lower = article["description"].lower()
    
    # Prominence keywords
    breaking_kw = ["breaking", "announces", "unveils", "launch", "discovers", "breakthrough", "major", "critical", "historic", "shocks"]
    for kw in breaking_kw:
        if kw in title_lower:
            score += 15
        elif kw in desc_lower:
            score += 5
            
    # Length of description (indicates richer details)
    if len(article["description"]) > 150:
        score += 5
        
    # Recency bonus (if publish date is parsed successfully)
    try:
        pub_time = datetime.datetime.fromisoformat(article["published_at"].replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        diff_hours = (now - pub_time).total_seconds() / 3600.0
        
        if diff_hours < 4:
            score += 20
        elif diff_hours < 12:
            score += 10
        elif diff_hours > 48:
            score -= 20  # penalty for older news
    except Exception:
        pass
        
    return score

def deduplicate_and_save(articles):
    """Save unique articles to DynamoDB, filtering duplicates in the database."""
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)
    
    saved_count = 0
    new_articles = []
    
    for article in articles:
        # Generate MD5 hash of URL as unique ID
        url_hash = hashlib.md5(article["url"].encode("utf-8")).hexdigest()
        article["url_hash"] = url_hash
        article["active"] = "1"  # Dummy PK for querying all latest news via GSI
        article["created_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        article["score"] = calculate_score(article)
        
        # Check if already exists in DynamoDB
        try:
            res = table.get_item(Key={"url_hash": url_hash, "published_at": article["published_at"]})
            if "Item" in res:
                continue
                
            # Save new article
            table.put_item(Item=article)
            saved_count += 1
            new_articles.append(article)
        except Exception as e:
            logger.error(f"Error checking/saving article {article['title']}: {e}")
            
    logger.info(f"Deduplicated {len(articles)} articles. Saved {saved_count} new articles to DynamoDB.")
    return new_articles

def send_telegram_briefing(bot_token, chat_id, articles):
    """Send the formatted daily news briefing to the configured Telegram channel/chat using HTML parse mode."""
    if not bot_token or not chat_id:
        logger.warning("Telegram Bot Token or Chat ID not configured. Skipping briefing.")
        return
        
    if not articles:
        logger.info("No articles to send in the briefing.")
        return
        
    # Format the message in HTML format
    message = "<b>🔥 Daily Trending News Digest 🔥</b>\n\n"
    
    for i, article in enumerate(articles, 1):
        title = article.get("title", "")
        url = article.get("url", "")
        source = article.get("source", "")
        category = article.get("category", "")
        score = article.get("score", 100)
        
        # Escape HTML special characters
        title_escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        source_escaped = source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        category_escaped = category.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Format line: index. [Category] Title (Source) - Score
        # With hyperlink on title if url is valid
        if url:
            item_str = f"{i}. [{category_escaped}] <a href=\"{url}\">{title_escaped}</a> (<i>{source_escaped}</i>) [Score: {score}]\n\n"
        else:
            item_str = f"{i}. [{category_escaped}] <b>{title_escaped}</b> (<i>{source_escaped}</i>) [Score: {score}]\n\n"
            
        # Telegram message limit is 4096 characters. Let's make sure we don't exceed it.
        if len(message) + len(item_str) + 100 > 4096:
            break
        message += item_str
        
    if DASHBOARD_URL:
        dashboard_escaped = DASHBOARD_URL.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        message += f"\n🌐 <a href=\"{dashboard_escaped}\">View full dashboard</a>"
        
    # Post request to Telegram API
    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            telegram_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode())
            if not res_data.get("ok"):
                logger.error(f"Telegram API error: {res_data}")
            else:
                logger.info("Successfully sent news briefing to Telegram.")
    except Exception as e:
        logger.error(f"Failed to send Telegram briefing: {e}")

def lambda_handler(event, context):
    """Main Lambda Entry Point."""
    logger.info(f"Received event: {json.dumps(event)}")
    
    # 1. Fetch credentials
    bot_token, chat_id, news_api_key = get_secrets()
    
    # 2. Fetch all candidates
    all_articles = []
    
    # Try fetching via NewsAPI first if configured
    if news_api_key:
        logger.info("Fetching articles from NewsAPI...")
        all_articles.extend(fetch_newsapi(news_api_key))
        
    # Fetch from RSS feeds as default/fallback or primary if NewsAPI key is missing
    logger.info("Fetching articles from RSS feeds...")
    for category, feed_url in RSS_FEEDS.items():
        all_articles.extend(fetch_rss_feed(category, feed_url))
        
    if not all_articles:
        logger.warning("No articles fetched from any source.")
        return {"statusCode": 200, "body": "No articles fetched."}
        
    # 3. Deduplicate and Save to DynamoDB
    new_saved = deduplicate_and_save(all_articles)
    
    # 4. Fetch the highest ranked articles from DynamoDB across categories to send in briefing
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)
    
    # Get recent articles from the last 24 hours
    day_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).isoformat() + "Z"
    
    briefing_articles = []
    try:
        # Query GlobalIndex for active = '1' sorted by published_at
        res = table.query(
            IndexName="GlobalIndex",
            KeyConditionExpression=Key("active").eq("1") & Key("published_at").gt(day_ago),
            ScanIndexForward=False, # Descending order
            Limit=50
        )
        
        # Sort by score descending to get top trending news
        db_articles = res.get("Items", [])
        db_articles.sort(key=lambda x: int(x.get("score", 100)), reverse=True)
        briefing_articles = db_articles[:15] # Top 15 articles across categories
    except Exception as e:
        logger.error(f"Error reading top articles from DynamoDB: {e}")
        new_saved.sort(key=lambda x: x.get("score", 100), reverse=True)
        briefing_articles = new_saved[:15]
        
    # 5. Send briefing
    send_telegram_briefing(bot_token, chat_id, briefing_articles)
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Successfully processed {len(all_articles)} candidates.",
            "new_saved": len(new_saved),
            "briefing_sent": len(briefing_articles) > 0
        })
    }
