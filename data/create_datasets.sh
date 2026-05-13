#!/bin/bash
# Create QuickSight datasets (SPICE) from S3 CSVs.
# S3 physical tables require all columns to be STRING; we cast via LogicalTable operations.
set -euo pipefail

ACCOUNT_ID=${AWS_ACCOUNT_ID:?Set AWS_ACCOUNT_ID}
REGION=us-west-2
ADMIN_ARN="arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:user/default/${QS_ADMIN_USER_NAME:?Set QS_ADMIN_USER_NAME}"

PERMS=$(cat <<JSON
[{"Principal": "${ADMIN_ARN}", "Actions": ["quicksight:DescribeDataSet","quicksight:DescribeDataSetPermissions","quicksight:PassDataSet","quicksight:DescribeIngestion","quicksight:ListIngestions","quicksight:UpdateDataSet","quicksight:DeleteDataSet","quicksight:CreateIngestion","quicksight:CancelIngestion","quicksight:UpdateDataSetPermissions"]}]
JSON
)

# Create dataset with all string input columns + logical table cast operations.
# Args:
#   1: dataset id
#   2: dataset name
#   3: data source id
#   4: column names (space-separated)
#   5: cast operations JSON array (e.g. '[{"ColumnName":"amount","NewColumnType":"DECIMAL"}]')
create_ds() {
    local ds_id="$1"
    local ds_name="$2"
    local src_id="$3"
    local -a cols=($4)
    local casts="$5"

    local cols_json=""
    for c in "${cols[@]}"; do
        cols_json+="{\"Name\":\"${c}\",\"Type\":\"STRING\"},"
    done
    cols_json="[${cols_json%,}]"

    local physical_table=$(cat <<JSON
{
    "src": {
        "S3Source": {
            "DataSourceArn": "arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:datasource/${src_id}",
            "InputColumns": ${cols_json}
        }
    }
}
JSON
)

    local cast_ops=""
    for row in $(echo "$casts" | python3 -c 'import json,sys; d=json.load(sys.stdin);
for r in d: print(f"{r[\"ColumnName\"]}|{r[\"NewColumnType\"]}")'); do
        local name=${row%|*}
        local typ=${row#*|}
        cast_ops+="{\"CastColumnTypeOperation\": {\"ColumnName\": \"${name}\", \"NewColumnType\": \"${typ}\"}},"
    done
    cast_ops="[${cast_ops%,}]"

    local logical_table=$(cat <<JSON
{
    "main": {
        "Alias": "${ds_name}",
        "Source": {"PhysicalTableId": "src"},
        "DataTransforms": ${cast_ops}
    }
}
JSON
)

    aws quicksight create-data-set \
        --aws-account-id "$ACCOUNT_ID" \
        --region "$REGION" \
        --data-set-id "$ds_id" \
        --name "$ds_name" \
        --physical-table-map "$physical_table" \
        --logical-table-map "$logical_table" \
        --import-mode SPICE \
        --permissions "$PERMS" \
        --output text --query '[DataSetId,Arn,IngestionArn]' 2>&1
}

echo "[1/5] clients..."
create_ds "clearone-clients" "ClearOne Clients" "clearone-clients-src" \
    "client_id first_name last_name state enrollment_date total_enrolled_debt monthly_deposit enrolled_accounts status enrollment_source assigned_specialist assigned_negotiator assigned_cs" \
    '[{"ColumnName":"enrollment_date","NewColumnType":"DATETIME"},{"ColumnName":"total_enrolled_debt","NewColumnType":"DECIMAL"},{"ColumnName":"monthly_deposit","NewColumnType":"DECIMAL"},{"ColumnName":"enrolled_accounts","NewColumnType":"INTEGER"}]'
echo

echo "[2/5] negotiations..."
create_ds "clearone-negotiations" "ClearOne Negotiations" "clearone-negotiations-src" \
    "negotiation_id client_id creditor original_balance settlement_amount settlement_percentage savings outcome negotiation_date negotiator_id" \
    '[{"ColumnName":"original_balance","NewColumnType":"DECIMAL"},{"ColumnName":"settlement_amount","NewColumnType":"DECIMAL"},{"ColumnName":"settlement_percentage","NewColumnType":"DECIMAL"},{"ColumnName":"savings","NewColumnType":"DECIMAL"},{"ColumnName":"negotiation_date","NewColumnType":"DATETIME"}]'
echo

echo "[3/5] payments..."
create_ds "clearone-payments" "ClearOne Payments" "clearone-payments-src" \
    "payment_id client_id draft_date amount status failure_reason" \
    '[{"ColumnName":"draft_date","NewColumnType":"DATETIME"},{"ColumnName":"amount","NewColumnType":"DECIMAL"}]'
echo

echo "[4/5] agent_performance..."
create_ds "clearone-agent-performance" "ClearOne Agent Performance" "clearone-agent-performance-src" \
    "date agent_id agent_name role office team calls_handled talk_time_minutes enrollments_signed enrolled_debt_total settlements_closed settlement_savings_total client_contacts csat_score" \
    '[{"ColumnName":"date","NewColumnType":"DATETIME"},{"ColumnName":"calls_handled","NewColumnType":"INTEGER"},{"ColumnName":"talk_time_minutes","NewColumnType":"DECIMAL"},{"ColumnName":"enrollments_signed","NewColumnType":"INTEGER"},{"ColumnName":"enrolled_debt_total","NewColumnType":"DECIMAL"},{"ColumnName":"settlements_closed","NewColumnType":"INTEGER"},{"ColumnName":"settlement_savings_total","NewColumnType":"DECIMAL"},{"ColumnName":"client_contacts","NewColumnType":"INTEGER"},{"ColumnName":"csat_score","NewColumnType":"DECIMAL"}]'
echo

echo "[5/5] call_activity..."
create_ds "clearone-call-activity" "ClearOne Call Activity" "clearone-call-activity-src" \
    "date hour queue calls_offered calls_answered calls_abandoned service_level_pct avg_wait_seconds avg_handle_seconds" \
    '[{"ColumnName":"date","NewColumnType":"DATETIME"},{"ColumnName":"hour","NewColumnType":"INTEGER"},{"ColumnName":"calls_offered","NewColumnType":"INTEGER"},{"ColumnName":"calls_answered","NewColumnType":"INTEGER"},{"ColumnName":"calls_abandoned","NewColumnType":"INTEGER"},{"ColumnName":"service_level_pct","NewColumnType":"DECIMAL"},{"ColumnName":"avg_wait_seconds","NewColumnType":"DECIMAL"},{"ColumnName":"avg_handle_seconds","NewColumnType":"DECIMAL"}]'
echo
echo "All datasets created."
