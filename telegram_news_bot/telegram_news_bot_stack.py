import os
import sys
import json
import shutil
import subprocess
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_s3_deployment as s3_deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_secretsmanager as secretsmanager,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct

def bundle_lambda(src_dir: str, build_dir: str, req_file: str):
    """Bundles Lambda directory and pip installs dependencies for Linux execution."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abs_src = os.path.join(project_root, src_dir)
    abs_build = os.path.join(project_root, build_dir)
    abs_req = os.path.join(project_root, req_file)
    
    # Recreate build directory
    if os.path.exists(abs_build):
        shutil.rmtree(abs_build)
    os.makedirs(abs_build)
    
    # Copy source files
    for item in os.listdir(abs_src):
        s = os.path.join(abs_src, item)
        d = os.path.join(abs_build, item)
        if os.path.isdir(s):
            if item != "__pycache__":
                shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
            
    # Install dependencies targeting standard AWS Lambda Linux platform
    if os.environ.get("SKIP_PIP_BUNDLE") == "true":
        print(f"Skipping dependency install for {src_dir} (SKIP_PIP_BUNDLE active).")
        return

    if os.path.exists(abs_req):
        print(f"Bundling dependencies for {src_dir} into {build_dir}...")
        try:
            subprocess.run([
                sys.executable, "-m", "pip", "install",
                "-r", abs_req,
                "-t", abs_build,
                "--platform", "manylinux2014_x86_64",
                "--only-binary=:all:",
                "--implementation", "cp",
                "--python-version", "3.11",
                "--no-cache-dir"
            ], check=True)
        except Exception as e:
            print(f"Platform-specific pip install failed, falling back to simple local install: {e}")
            subprocess.run([
                sys.executable, "-m", "pip", "install",
                "-r", abs_req,
                "-t", abs_build,
                "--no-cache-dir"
            ], check=True)


class TelegramNewsBotStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. Bundling lambdas locally during synthesis
        print("Preparing and bundling Lambda functions...")
        bundle_lambda("backend/fetcher", ".build/fetcher", "backend/fetcher/requirements.txt")
        bundle_lambda("backend/api", ".build/api", "backend/api/requirements.txt")

        # 2. AWS Secrets Manager Secret for credentials
        secrets = secretsmanager.Secret(
            self, "TelegramNewsBotSecrets",
            secret_name="TelegramNewsBotSecrets",
            description="Secrets for Telegram Trending News Bot (bot token, chat ID, and news API key)",
        )

        # 3. DynamoDB Table for storing news articles
        table = dynamodb.Table(
            self, "NewsArticlesTable",
            table_name="NewsArticles",
            partition_key=dynamodb.Attribute(name="url_hash", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="published_at", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # GSI: CategoryIndex - query latest articles by category
        table.add_global_secondary_index(
            index_name="CategoryIndex",
            partition_key=dynamodb.Attribute(name="category", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="published_at", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # GSI: GlobalIndex - query latest articles across all categories (using active='1')
        table.add_global_secondary_index(
            index_name="GlobalIndex",
            partition_key=dynamodb.Attribute(name="active", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="published_at", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # 4. S3 Bucket for Hosting Frontend Web Assets
        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
        )

        # CloudFront Origin Access Identity (OAI) for S3 access
        oai = cloudfront.OriginAccessIdentity(self, "FrontendOAI")
        frontend_bucket.grant_read(oai)

        # 5. Fetcher Lambda Function
        fetcher_lambda = _lambda.Function(
            self, "NewsFetcherLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_function.lambda_handler",
            code=_lambda.Code.from_asset(".build/fetcher"),
            timeout=Duration.seconds(120),
            memory_size=256,
            environment={
                "DYNAMODB_TABLE": table.table_name,
                "SECRETS_NAME": secrets.secret_name,
            }
        )

        # 6. FastAPI Lambda Function
        api_lambda = _lambda.Function(
            self, "NewsApiLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="main.handler",
            code=_lambda.Code.from_asset(".build/api"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "DYNAMODB_TABLE": table.table_name,
                "FETCHER_LAMBDA_NAME": fetcher_lambda.function_name,
            }
        )

        # 7. API Gateway (REST API) for backend API calls
        api_gateway = apigw.LambdaRestApi(
            self, "NewsApiGateway",
            handler=api_lambda,
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS
            )
        )


        # 8. Permissions and Security
        table.grant_read_write_data(fetcher_lambda)
        table.grant_read_data(api_lambda)
        secrets.grant_read(fetcher_lambda)
        fetcher_lambda.grant_invoke(api_lambda)

        # 9. EventBridge Rule - Schedule fetcher twice daily (8:00 AM & 8:00 PM UTC)
        rule = events.Rule(
            self, "FetcherCronRule",
            schedule=events.Schedule.cron(minute="0", hour="8,20", month="*", day="*", year="*")
        )
        rule.add_target(targets.LambdaFunction(fetcher_lambda))

        # Outputs
        cdk.CfnOutput(self, "WebDashboardURL", value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "ApiGatewayEndpoint", value=api_gateway.url)
