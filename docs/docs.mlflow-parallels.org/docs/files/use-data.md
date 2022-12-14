# Data Handling

*Concurrent* includes extensive data management capabilities. Here are the highlights:

- Most python libraries are written to read and write local files. Access to data in **s3 or other object stores** has to be hand written by users of the library. Concurrent eases this burden by making Cloud Object Store contents available in the container in a local directory. Python code and libraries can read these files using time tested python calls such as *open*. The *concurrent_core* API described in the next section is the mechanism by which this functionality is exposed to users
- Partitioning the data is an important part of parallelization of compute in Concurrent. The *concurrent_core* API is the system used to interface with the partitioning logic

## concurrent_core API

The *concurrent_core* API includes four functions:

### list(path, input_name=None)

This is the main interface to the data

```
from concurrent import concurrent_core
df = concurrent_core.list(path, input_name=None)

```

The list call returns a *Pandas Dataframe* with at least the following columns. Other columns may be present if the underlying storage has additional metadata

- **FileName**: contains the prefix in the Object Store (s3) bucket
- **FileSize**: size of the object in the Object Store
- **FileLastModified**: last modified date
- **FileVersionId**: object version, if the object store supports object versioning
- **partitioning_key**: the key that was generated by the partitioning function

Example usage:

```
df = concurrent_core.list(None, input_name='cowrie')
```
This example is from the honeypot sample included with Concurrent at *https://github.com/concurrent-ai/concurrent-examples.git*, subdirectory honeypot. In the node1's *honeypot.py* the above line is used to list the input named *cowrie*. Note that when defining the DAG, the same name *cowrie* is utilized. That is how the name of the input as defined in the DAG is connected to the code.

### get_local_paths(df)

get_local_paths converts the DataFrame returned by list into a set of local files.

```
concurrent_core.get_local_paths(df)
```

*get_local_paths* returns an array of local paths. Input to this function is *df*, the DataFrame returned by a previous call to list. Each entry in the array corresponds to an entry in the DataFrame df.

Example usage:
```
lp = concurrent_core.get_local_paths(df)
print('Local paths=' + str(lp))
```
In this snippet, taken from the same sample code, we call *get_local_paths* with the Pandas DataFrame that *list* returned to us. The result from *get_local_paths* is an array of filenames. e.g:

```
Local paths=[
'/tmp/tmppfcxfbiz/part-0/00211a641c6e-2e1958d1b469b42f9be8601812714030a70d625383cd3035a9ab806ce22110e8',
'/tmp/tmppfcxfbiz/part-0/00211a641c6e-4ed8d2115d33334ecd4c0e5cfa7a5b0c792529e3c94bfc0b1c14630df5cfb1ee'
]
```

From the output, you can see that the s3 object named *00211a641c6e-2e1958d1b469b42f9be8601812714030a70d625383cd3035a9ab806ce22110e8* is made available to node2 code as local file */tmp/tmppfcxfbiz/part-0/00211a641c6e-2e1958d1b469b42f9be8601812714030a70d625383cd3035a9ab806ce22110e8*.

### concurrent_log_artifact(local_path, artifact_path, **kwargs)

log_artifact logs a single file as an MLflow artifact for this run.

```
concurrent_core.concurrent_log_artifact(local_path, artifact_path, **kwargs)
```
Parameters:

- **local_path**: Filename in local filesystem
- **artifact_path**: subdirectory in the MLflow artifact location for this run
- **kwargs**: List of keyword arguments that are passed to subsequent processing steps as columns in the PandasDataFrame returned by *concurrent_core.list*

### concurrent_log_artifacts(local_dir, artifact_path, **kwargs)

log_artifact logs a directory of files as MLflow artifacts for this run.

```
concurrent_core.concurrent_log_artifacts(local_dir, artifact_path, **kwargs)
```

Parameters:

- **local_dir**: Directory in local filesystem. The contents are all logged to MLflow
- **artifact_path**: subdirectory in the MLflow artifact location for this run
- **kwargs**: List of keyword arguments that are passed to subsequent processing steps as columns in the PandasDataFrame returned by *concurrent_core.list*


## Partitioning Data for Parallel Processing

Concurrent includes the capability to partition(divide) data and concurrently process the partitioned data using multiple containers running the MLproject for that node in the DAG.

The system includes several partitioners included for convenience. They are:

- No partitioner
- Directory
- Object
- Custom

### No Partitioner

This option is used when there is only one single container for this node in the DAG. No parallelization is specified, hence no partitioning is required.

### Directory Partitioner

In this case, the data is partitioned by directory. Hence all the files in that subdirectory can be processed by a single container. For example, if there are directories with DICOM images, each directory containing all the images for a single patient, it is useful to have all the images in that directory be processed by a single container.

### Object Partitioner

The object partitioner considers each file as one partition of the data.

### Custom Partitioner

Custom partitioners greatly enhance the capability of the system. Simply stated, a custom partitioner is python lambda that is used to partition data. An example illustrates this best.

#### Simple Custom Partitioner Example

[![](https://docs.concurrent-ai.org/images/data/data1.png?raw=true)](https://docs.concurrent-ai.org/images/data/data1.png?raw=true)

In the above example, the partitioner is specified as:
```
lambda: row:row['FileName']
```
This implements the Object partitioner listed above, wherein each object or file is considered as a partition of the data

#### A More Complex Custom Partitioner Example

[![](https://docs.concurrent-ai.org/images/data/data2.png?raw=true)](https://docs.concurrent-ai.org/images/data/data2.png?raw=true)

In this example, the lambda for partitioning is specified as 

```
lambda row:row['FileName'].split('/')[-1].split('-')[0]
```

The requirement for this partitioning is as follows. Files are named *session_id-uuid*. There are multiple files per session_id and all files for any given session_id should be processed by the same partition. Here is an example listing of files in s3 prefix *honeypot/test/'* in the test bucket:

```
2022-09-27 18:44:58        248 0004c5ca1fb1-1aaa578257890043c76e94404d3832329222b0791a2a6d9894a167c3a70cf0e7
2022-09-27 18:45:00       1478 0004c5ca1fb1-36501938368a1d60e1f18aa978d558b6c0c259b2fe77cb1728f148c59faff705
2022-09-27 18:44:59        193 0004c5ca1fb1-495209c6a991d1423f936c91f3d071dc8d9d64dc9884878604f0ec351d86149c
2022-09-27 18:44:59        222 0004c5ca1fb1-890c34b7ee95de1f6701de9286063502850713d836d1054415a126d070a04fda
2022-09-27 18:45:00        318 0004c5ca1fb1-c0f721dfdd76254114d517777140eecd97518eddf4f0ce24fbd6c34a668abc62
2022-09-27 18:45:01        185 0004c5ca1fb1-c23847f8db947c317d4b403f75277bb4e688a792253f102c8824a2b42d4b57fa
2022-09-27 18:45:01        215 0004c5ca1fb1-c444cd34b212445622a254603a25c9ec31c70766a0946c55a03cc56ca0e724dc
2022-09-27 18:45:01        502 0004c5ca1fb1-cfb191550a2a9221e5bc4168b1a22db13850425455bb48cdfeeb102bac811c48
2022-09-27 18:45:02        215 001428ca1ac2-18d0b9d39db5c331fd2ed2400bc31d5cb7777dcbb697500bcdc555e59e472c90
2022-09-27 18:45:03        222 001428ca1ac2-86b6a5dec9126d5748d16162fd2356dd8b62a3aa34dfe68a762457f37189571a
2022-09-27 18:45:03        220 001428ca1ac2-d05b797d792cb329b62720dc2b7cc02ca49bd3ab722e4269c0c3173617c69c20
2022-09-27 18:45:04       1478 001428ca1ac2-d310005af3eae9f96305b9cf063374c418cece49380006ca8b903e825cd50984
2022-09-27 18:45:05        318 001428ca1ac2-e55bb3ea697998ae2b18ed068d12fb32f405156b4496cf0212302e4b3e40ebcf
2022-09-27 18:45:05        225 0017296413d1-2fa010c3f1f6f5d88aa5898706be0b120736e05df922a38d7278fa3eaf5e8d0d
2022-09-27 18:45:06        232 0017296413d1-94006e240c6442846b62d548c9fe52e4f2f46c298209ab5bb304f4dbe0baf0a2
2022-09-27 18:45:09        320 0017296413d1-e8917bbeec63750414b0fd5e02741ef3ee83e434be49315a68a6f29d223bf327
```

In the example, the eight files for sessionid *0004c5ca1fb1* should be processed by the same container

*row['FileName']* contains
```
honeypot/test/0004c5ca1fb1-1aaa578257890043c76e94404d3832329222b0791a2a6d9894a167c3a70cf0e7
```
The lambda function splits the path by */* and chooses the last portion of the filename, then it splits that by *-* and chooses the first portion, which happens to be the *session_id*. With *session_id* cut out of the full pathname, it is then used as the partition function and all files of a particular *session_id* are sent to the same container for processing
