import sys
from unittest.mock import MagicMock

# Globally mock boto3 and its submodules to isolate unit tests from AWS credentials
mock_boto3 = MagicMock()
mock_dynamodb = MagicMock()
mock_conditions = MagicMock()

# Setup mock objects
mock_key = MagicMock()
mock_conditions.Key = mock_key

# Mock the resource Table response chain
mock_table = MagicMock()
mock_boto3.resource.return_value.Table.return_value = mock_table

# Bind mock modules to sys.modules
sys.modules['boto3'] = mock_boto3
sys.modules['boto3.dynamodb'] = mock_dynamodb
sys.modules['boto3.dynamodb.conditions'] = mock_conditions
