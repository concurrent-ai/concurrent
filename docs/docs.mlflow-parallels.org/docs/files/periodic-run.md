# Periodic Run

*Concurrent* includes the ability to run DAGs periodically, on a schedule.

## Periodic Run CLI

Concurrent Periodic Run CLI is part of the concurrent plugin. Here's the help message:

```
$ python -m concurrent_plugin.periodic_run -h
usage: periodic_run.py [-h] [--periodic_run_name PERIODIC_RUN_NAME] [--schedule SCHEDULE] [--schedule_type {once,hourly,daily,weekly,monthly,yearly}] [--experiment_id EXPERIMENT_ID] [--dagid DAGID] {add,delete,list}

positional arguments:
  {add,delete,list}

optional arguments:
  -h, --help            show this help message and exit
  --periodic_run_name PERIODIC_RUN_NAME
  --schedule SCHEDULE   format is a_b_c_d_e_f where a=minutes(0-59), b=hour(0-23), c=day_of_month(1-31), d=month(1-12), e=day_of_week(0-7, 0 is Sunday)
  --schedule_type {once,hourly,daily,weekly,monthly,yearly}
  --experiment_id EXPERIMENT_ID
  --dagid DAGID

Example: python -m concurrent_plugin.periodic_run add --periodic_run_name test1 --schedule "06_22_*_*_*_*" --schedule_type once --dagid DAG1665114786385 --experiment_id 7
```

### Create

```
python -m concurrent_plugin.periodic_run add --periodic_run_name cw-hourly --schedule "53_*_*_*_*_*" --schedule_type hourly --dagid DAG1670863769990 --experiment_id 15
```

### Delete

```
python -m concurrent_plugin.periodic_run delete --periodic_run_name cw-hourly
```

### List

```
python -m concurrent_plugin.periodic_run list
```

## Periodic Run Data

Periodic runs are useful for processing data that was received/ingested in the time period since the last run. Concurrent provides assistance for this purpose.

### InfinSlice

If the input to any node in the DAG is specified as a timeslice, for example infinslice, then the Concurrent server will automatically modify the period to indicate the interval from the previous run to the start of this current run

### Non InfinSlice

For all other types of storage/data sources, Concurrent will set two different environment variables in all DAG nodes:

```
PERIDOIC_RUN_FREQUENCY
PERIDOIC_RUN_START_TIME
```

**PERIDOIC_RUN_FREQUENCY** is one of **once,hourly,daily,weekly,monthly,yearly**

**PERIDOIC_RUN_START_TIME** is the time in milliseconds since the epoch
