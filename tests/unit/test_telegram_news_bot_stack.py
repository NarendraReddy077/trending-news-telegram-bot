import aws_cdk as core
import aws_cdk.assertions as assertions

from telegram_news_bot.telegram_news_bot_stack import TelegramNewsBotStack

def test_cdk_resources_created():
    import os
    os.environ["SKIP_PIP_BUNDLE"] = "true"
    app = core.App()
    stack = TelegramNewsBotStack(app, "telegram-news-bot-test")
    template = assertions.Template.from_stack(stack)

    # 1. Verify DynamoDB Table is created
    template.resource_count_is("AWS::DynamoDB::Table", 1)
    
    # Verify GSIs on the table
    template.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": "NewsArticles",
        "KeySchema": [
            {"AttributeName": "url_hash", "KeyType": "HASH"},
            {"AttributeName": "published_at", "KeyType": "RANGE"}
        ]
    })

    # 2. Verify Secrets Manager Secret is created
    template.resource_count_is("AWS::SecretsManager::Secret", 1)
    template.has_resource_properties("AWS::SecretsManager::Secret", {
        "Name": "TelegramNewsBotSecrets"
    })

    # 3. Verify S3 Buckets are created
    template.has_resource("AWS::S3::Bucket", {})

    # 4. Verify Lambda Functions are created
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "lambda_function.lambda_handler",
        "Runtime": "python3.11"
    })
    
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "main.handler",
        "Runtime": "python3.11"
    })

    # 5. Verify API Gateway RestApi
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)

    # 6. Verify CloudFront Distribution
    template.resource_count_is("AWS::CloudFront::Distribution", 1)

    # 7. Verify EventBridge Cron Scheduler Rule
    template.resource_count_is("AWS::Events::Rule", 1)
    template.has_resource_properties("AWS::Events::Rule", {
        "ScheduleExpression": "cron(0 8,20 * * ? *)"
    })
