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
aws dynamodb create-backup --table-name parallels-k8s-clusters --backup-name parallels-k8s-clusters.backup
```

Now, install the new version of the stack. Once the new version has been installed, remove the tables *mlflow-parallels-dag*, *concurrent-storage-credentials*, and *parallels-k8s-clusters* using the aws web console

Finally, restore the tables from backup.

```
aws dynamodb restore-table-from-backup --target-table-name mlflow-parallels-dag --backup-arn arn:aws:dynamodb:us-east-1:888888888888:table/mlflow-parallels-dag/backup/02345664455553-f7f1d528 
aws dynamodb restore-table-from-backup --target-table-name concurrent-storage-credentials  --backup-arn  arn:aws:dynamodb:us-east-1:888888888888:table/concurrent-storage-credentials/backup/02342342423424-b685a100
aws dynamodb restore-table-from-backup --target-table-name parallels-k8s-clusters --backup-arn  arn:aws:dynamodb:us-east-1:888888888888:table/parallels-k8s-clusters/backup/02342342423424-b685a100

```
