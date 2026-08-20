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

def safe_rmtree(path: str):
    """Safely removes a directory tree, retrying and fixing read-only files on Windows."""
    import stat
    import time

    def remove_readonly(func, p, excinfo):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    if not os.path.exists(path):
        return

    for i in range(5):
        try:
            shutil.rmtree(path, onerror=remove_readonly)
            return
        except OSError as e:
            if i == 4:
                raise e
            time.sleep(0.2 * (i + 1))


def bundle_lambda(src_dir: str, build_dir: str, req_file: str):
    """Bundles Lambda directory and pip installs dependencies for Linux execution."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abs_src = os.path.join(project_root, src_dir)
    abs_build = os.path.join(project_root, build_dir)
    abs_req = os.path.join(project_root, req_file)
    
    # Determine cache directory for dependencies
    dir_name = os.path.basename(build_dir)
    abs_cache = os.path.join(project_root, ".build", "cache", dir_name)
    cache_req = os.path.join(abs_cache, "requirements.txt")
    
    # Check if cached dependencies exist and requirements.txt matches
    run_pip = True
    if os.path.exists(abs_req):
        if os.path.exists(abs_cache) and os.path.exists(cache_req):
            try:
                with open(abs_req, "r") as f1, open(cache_req, "r") as f2:
                    if f1.read().strip() == f2.read().strip():
                        run_pip = False
            except Exception:
                run_pip = True

    if run_pip and os.environ.get("SKIP_PIP_BUNDLE") != "true":
        print(f"Installing dependencies for {src_dir} (cache missing or requirements changed)...")
        safe_rmtree(abs_cache)
        os.makedirs(abs_cache)
        
        if os.path.exists(abs_req):
            try:
                subprocess.run([
                    sys.executable, "-m", "pip", "install",
                    "-r", abs_req,
                    "-t", abs_cache,
                    "--platform", "manylinux2014_x86_64",
                    "--only-binary=:all:",
                    "--implementation", "cp",
                    "--python-version", "3.11"
                ], check=True)
            except Exception as e:
                print(f"Platform-specific pip install failed, falling back to simple local install: {e}")
                subprocess.run([
                    sys.executable, "-m", "pip", "install",
                    "-r", abs_req,
                    "-t", abs_cache
                ], check=True)
            
            # Copy requirements.txt to cache directory to track changes
            shutil.copy2(abs_req, cache_req)
    else:
        if os.environ.get("SKIP_PIP_BUNDLE") == "true":
            print(f"Skipping dependency install for {src_dir} (SKIP_PIP_BUNDLE active).")
        else:
            print(f"Using cached dependencies for {src_dir}.")

    # Recreate build directory
    safe_rmtree(abs_build)
    os.makedirs(abs_build)

    # Copy dependencies from cache to build directory
    if os.path.exists(abs_cache):
        for item in os.listdir(abs_cache):
            s = os.path.join(abs_cache, item)
            d = os.path.join(abs_build, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

    # Copy Lambda source files
    for item in os.listdir(abs_src):
        s = os.path.join(abs_src, item)
        d = os.path.join(abs_build, item)
        if os.path.isdir(s):
            if item != "__pycache__":
                shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)



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

        # Check if CloudFront should be disabled
        disable_cloudfront = (
            os.environ.get("DISABLE_CLOUDFRONT") == "true" or
            self.node.try_get_context("disable_cloudfront") == "true"
        )

        # 4. S3 Bucket for Hosting Frontend Web Assets
        if disable_cloudfront:
            frontend_bucket = s3.Bucket(
                self, "FrontendBucket",
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_objects=True,
                website_index_document="index.html",
                public_read_access=True,
                block_public_access=s3.BlockPublicAccess(
                    block_public_acls=False,
                    block_public_policy=False,
                    ignore_public_acls=False,
                    restrict_public_buckets=False
                ),
                encryption=s3.BucketEncryption.S3_MANAGED,
            )
        else:
            frontend_bucket = s3.Bucket(
                self, "FrontendBucket",
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_objects=True,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                encryption=s3.BucketEncryption.S3_MANAGED,
            )

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

        # 8. CloudFront Distribution
        if not disable_cloudfront:
            # S3BucketOrigin with OAC (Origin Access Control) is the modern standard replacing S3Origin with OAI
            s3_origin = origins.S3BucketOrigin.with_origin_access_control(
                frontend_bucket
            )


            api_domain = f"{api_gateway.rest_api_id}.execute-api.{self.region}.amazonaws.com"
            api_origin = origins.HttpOrigin(
                api_domain,
                origin_path="/prod"
            )

            distribution = cloudfront.Distribution(
                self, "NewsDistribution",
                default_behavior=cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                ),
                additional_behaviors={
                    "/api/*": cloudfront.BehaviorOptions(
                        origin=api_origin,
                        viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                        allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                        cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                        origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER
                    )
                },
                default_root_object="index.html"
            )

            # Add live dashboard URL to fetcher Lambda's environment
            fetcher_lambda.add_environment("DASHBOARD_URL", f"https://{distribution.distribution_domain_name}")
        else:
            # S3 static website endpoint
            fetcher_lambda.add_environment("DASHBOARD_URL", frontend_bucket.bucket_website_url)

        # 9. S3 Deployment to push static files to S3 bucket
        api_url = api_gateway.url if disable_cloudfront else ""
        
        s3_deploy.BucketDeployment(
            self, "DeployFrontend",
            sources=[
                s3_deploy.Source.asset("frontend"),
                s3_deploy.Source.json_data("config.json", {
                    "apiBaseUrl": api_url.rstrip("/")
                })
            ],
            destination_bucket=frontend_bucket,
            distribution=None if disable_cloudfront else distribution,
            distribution_paths=None if disable_cloudfront else ["/*"]
        )

        # 10. Permissions and Security
        table.grant_read_write_data(fetcher_lambda)
        table.grant_read_data(api_lambda)
        secrets.grant_read(fetcher_lambda)
        fetcher_lambda.grant_invoke(api_lambda)

        # 11. EventBridge Rule - Schedule fetcher twice daily (8:00 AM & 8:00 PM UTC)
        rule = events.Rule(
            self, "FetcherCronRule",
            schedule=events.Schedule.cron(minute="0", hour="8,20", month="*", day="*", year="*")
        )
        rule.add_target(targets.LambdaFunction(fetcher_lambda))

        # Outputs
        if disable_cloudfront:
            cdk.CfnOutput(self, "WebDashboardURL", value=frontend_bucket.bucket_website_url)
        else:
            cdk.CfnOutput(self, "WebDashboardURL", value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "ApiGatewayEndpoint", value=api_gateway.url)

