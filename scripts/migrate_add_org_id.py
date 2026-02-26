#!/usr/bin/env python3
"""Migration: Add OrganizationID to existing DynamoDB records.

Scans LimsSamples and GenomicWorkflowState tables and adds
OrganizationID='ORG-LEGACY' to any items missing the attribute.

Usage:
    # Dry-run (default) — shows what would be changed
    python scripts/migrate_add_org_id.py --region us-east-1

    # Execute migration
    python scripts/migrate_add_org_id.py --region us-east-1 --execute

    # Use a specific org ID instead of ORG-LEGACY
    python scripts/migrate_add_org_id.py --region us-east-1 --org-id ORG-ACME --execute
"""

import argparse
import boto3
from boto3.dynamodb.conditions import Attr


DEFAULT_ORG_ID = "ORG-LEGACY"


def migrate_table(table, table_name, org_id, execute=False):
    """Scan a DynamoDB table and add OrganizationID to items missing it."""
    print(f"\nScanning {table_name}...")

    # Scan for items where OrganizationID doesn't exist
    scan_kwargs = {
        "FilterExpression": Attr("OrganizationID").not_exists(),
    }

    items_to_update = []
    response = table.scan(**scan_kwargs)
    items_to_update.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = table.scan(**scan_kwargs)
        items_to_update.extend(response.get("Items", []))

    print(f"  Found {len(items_to_update)} items without OrganizationID")

    if not items_to_update:
        return 0

    updated = 0
    for item in items_to_update:
        # Determine the key schema
        if "SampleID" in item and "Timestamp" in item:
            key = {"SampleID": item["SampleID"], "Timestamp": item["Timestamp"]}
        elif "SampleID" in item:
            key = {"SampleID": item["SampleID"]}
        else:
            print(f"  WARNING: Cannot determine key for item: {item}")
            continue

        sample_id = item.get("SampleID", "unknown")
        print(f"  {'[DRY RUN] ' if not execute else ''}Updating {sample_id} -> OrganizationID={org_id}")

        if execute:
            table.update_item(
                Key=key,
                UpdateExpression="SET OrganizationID = :org",
                ExpressionAttributeValues={":org": org_id},
            )
        updated += 1

    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Add OrganizationID to existing DynamoDB records"
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--org-id", default=DEFAULT_ORG_ID,
                        help=f"OrganizationID to assign (default: {DEFAULT_ORG_ID})")
    parser.add_argument("--execute", action="store_true",
                        help="Actually perform the migration (default: dry-run)")
    parser.add_argument("--lims-table", default="LimsSamples",
                        help="LimsSamples table name")
    parser.add_argument("--state-table", default="GenomicWorkflowState",
                        help="GenomicWorkflowState table name")
    args = parser.parse_args()

    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"=== Migration: Add OrganizationID ({mode}) ===")
    print(f"  Region: {args.region}")
    print(f"  OrganizationID: {args.org_id}")
    print(f"  Tables: {args.lims_table}, {args.state_table}")

    dynamodb = boto3.resource("dynamodb", region_name=args.region)

    lims_table = dynamodb.Table(args.lims_table)
    state_table = dynamodb.Table(args.state_table)

    total = 0
    total += migrate_table(lims_table, args.lims_table, args.org_id, execute=args.execute)
    total += migrate_table(state_table, args.state_table, args.org_id, execute=args.execute)

    print(f"\n=== Summary ===")
    print(f"  Total items {'updated' if args.execute else 'to update'}: {total}")
    if not args.execute and total > 0:
        print(f"\n  Run with --execute to apply changes.")
    print("Done!")


if __name__ == "__main__":
    main()
