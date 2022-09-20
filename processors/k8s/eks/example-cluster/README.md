# We create one single ClusterRole called k8s-service-role-for-parallels that all the ServiceAccounts are bound to
./create-service-role.sh
# We create one k8s ServiceAccount per namespace
./create-service-account.sh default
