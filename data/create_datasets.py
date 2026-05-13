"""Create QuickSight SPICE datasets with typed logical-table transforms.

S3 physical tables require all input columns to be STRING. We layer a logical
table on top with CastColumnTypeOperation transforms to get proper types.
"""
from __future__ import annotations

import sys
import boto3

import os

ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID") or boto3.client("sts").get_caller_identity()["Account"]
REGION = os.environ.get("AWS_REGION", "us-west-2")
DATA_BUCKET = os.environ.get("DEMO_DATA_BUCKET", f"clearone-demo-data-{ACCOUNT_ID}")
ADMIN_USER_NAME = os.environ.get("QS_ADMIN_USER_NAME")  # e.g. "Admin/your-iam-username"
if not ADMIN_USER_NAME:
    raise SystemExit("Set QS_ADMIN_USER_NAME (e.g. 'Admin/your-iam-username') from `aws quicksight list-users`")
ADMIN_ARN = f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:user/default/{ADMIN_USER_NAME}"

qs = boto3.client("quicksight", region_name=REGION)

PERMS = [
    {
        "Principal": ADMIN_ARN,
        "Actions": [
            "quicksight:DescribeDataSet",
            "quicksight:DescribeDataSetPermissions",
            "quicksight:PassDataSet",
            "quicksight:DescribeIngestion",
            "quicksight:ListIngestions",
            "quicksight:UpdateDataSet",
            "quicksight:DeleteDataSet",
            "quicksight:CreateIngestion",
            "quicksight:CancelIngestion",
            "quicksight:UpdateDataSetPermissions",
        ],
    }
]


def create_ds(ds_id: str, ds_name: str, src_id: str, columns: list[str], casts: list[tuple[str, str]]):
    input_columns = [{"Name": c, "Type": "STRING"} for c in columns]
    physical_table_map = {
        "src": {
            "S3Source": {
                "DataSourceArn": f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:datasource/{src_id}",
                "InputColumns": input_columns,
            }
        }
    }
    data_transforms = [
        {"CastColumnTypeOperation": {"ColumnName": name, "NewColumnType": new_type}}
        for name, new_type in casts
    ]
    if not data_transforms:
        # API requires at least 1 transform; use a no-op project
        data_transforms = [{"ProjectOperation": {"ProjectedColumns": columns}}]
    logical_table_map = {
        "main": {
            "Alias": ds_name,
            "Source": {"PhysicalTableId": "src"},
            "DataTransforms": data_transforms,
        }
    }
    try:
        qs.delete_data_set(AwsAccountId=ACCOUNT_ID, DataSetId=ds_id)
        print(f"  deleted existing {ds_id}")
    except qs.exceptions.ResourceNotFoundException:
        pass
    resp = qs.create_data_set(
        AwsAccountId=ACCOUNT_ID,
        DataSetId=ds_id,
        Name=ds_name,
        PhysicalTableMap=physical_table_map,
        LogicalTableMap=logical_table_map,
        ImportMode="SPICE",
        Permissions=PERMS,
    )
    print(f"  created {ds_id}: {resp['Arn']}")
    print(f"  ingestion: {resp.get('IngestionArn')}")


SPECS = [
    {
        "id": "clearone-clients",
        "name": "ClearOne Clients",
        "src": "clearone-clients-src",
        "columns": [
            "client_id", "first_name", "last_name", "state", "enrollment_date",
            "total_enrolled_debt", "monthly_deposit", "enrolled_accounts",
            "status", "enrollment_source", "assigned_specialist",
            "assigned_negotiator", "assigned_cs",
        ],
        "casts": [
            ("enrollment_date", "DATETIME"),
            ("total_enrolled_debt", "DECIMAL"),
            ("monthly_deposit", "DECIMAL"),
            ("enrolled_accounts", "INTEGER"),
        ],
    },
    {
        "id": "clearone-negotiations",
        "name": "ClearOne Negotiations",
        "src": "clearone-negotiations-src",
        "columns": [
            "negotiation_id", "client_id", "creditor", "original_balance",
            "settlement_amount", "settlement_percentage", "savings", "outcome",
            "negotiation_date", "negotiator_id",
        ],
        "casts": [
            ("original_balance", "DECIMAL"),
            ("settlement_amount", "DECIMAL"),
            ("settlement_percentage", "DECIMAL"),
            ("savings", "DECIMAL"),
            ("negotiation_date", "DATETIME"),
        ],
    },
    {
        "id": "clearone-payments",
        "name": "ClearOne Payments",
        "src": "clearone-payments-src",
        "columns": ["payment_id", "client_id", "draft_date", "amount", "status", "failure_reason"],
        "casts": [("draft_date", "DATETIME"), ("amount", "DECIMAL")],
    },
    {
        "id": "clearone-agent-performance",
        "name": "ClearOne Agent Performance",
        "src": "clearone-agent-performance-src",
        "columns": [
            "date", "agent_id", "agent_name", "role", "office", "team",
            "calls_handled", "talk_time_minutes", "enrollments_signed",
            "enrolled_debt_total", "settlements_closed", "settlement_savings_total",
            "client_contacts", "csat_score",
        ],
        "casts": [
            ("date", "DATETIME"),
            ("calls_handled", "INTEGER"),
            ("talk_time_minutes", "DECIMAL"),
            ("enrollments_signed", "INTEGER"),
            ("enrolled_debt_total", "DECIMAL"),
            ("settlements_closed", "INTEGER"),
            ("settlement_savings_total", "DECIMAL"),
            ("client_contacts", "INTEGER"),
            ("csat_score", "DECIMAL"),
        ],
    },
    {
        "id": "clearone-call-activity",
        "name": "ClearOne Call Activity",
        "src": "clearone-call-activity-src",
        "columns": [
            "date", "hour", "queue", "calls_offered", "calls_answered",
            "calls_abandoned", "service_level_pct", "avg_wait_seconds",
            "avg_handle_seconds",
        ],
        "casts": [
            ("date", "DATETIME"),
            ("hour", "INTEGER"),
            ("calls_offered", "INTEGER"),
            ("calls_answered", "INTEGER"),
            ("calls_abandoned", "INTEGER"),
            ("service_level_pct", "DECIMAL"),
            ("avg_wait_seconds", "DECIMAL"),
            ("avg_handle_seconds", "DECIMAL"),
        ],
    },
]


def main() -> None:
    for i, s in enumerate(SPECS, 1):
        print(f"[{i}/{len(SPECS)}] {s['name']}")
        create_ds(s["id"], s["name"], s["src"], s["columns"], s["casts"])
    print("all datasets created")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
