# Update Concurrent for MLflow Control Plane in AWS

## Update using CFT
Update of the control plane is accomplished by updating the CFT

## Backup DBs and Uninstall/Reinstall

If CFT update fails, the fall back option is as follows:

- backup the required db tables
- delete the CFT stack
- install the new version of the stack
- delete the tables that were backed up
- restore tables from backup

The required tables are:

- mlflow-parallels-dag
- concurrent-storage-credentials

Here are the commands for backup up the required tables.

```
aws dynamodb create-backup --table-name mlflow-parallels-dag --backup-name mlflow-parallels-dag.backup
aws dynamodb create-backup --table-name concurrent-storage-credentials --backup-name concurrent-storage-credentials.backup
```

And here's how to restore the tables once the stack has been uninstalled and re-installed. Note that the empty tables created by the CFT install should be deleted first

```
aws dynamodb restore-table-from-backup --target-table-name mlflow-parallels-dag --backup-arn arn:aws:dynamodb:us-east-1:888888888888:table/mlflow-parallels-dag/backup/02345664455553-f7f1d528 
aws dynamodb restore-table-from-backup --target-table-name concurrent-storage-credentials  --backup-arn  arn:aws:dynamodb:us-east-1:888888888888:table/concurrent-storage-credentials/backup/02342342423424-b685a100

```
