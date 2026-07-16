#Requires -Version 5.1

$script:XpjTestPostgresMarkerName = '.xpj-test-cluster.json'
$script:XpjTestPostgresMarkerKind = 'xiaopiaojia-test-postgres'
$script:XpjTestPostgresConsumerLeaseKind = 'xiaopiaojia-test-postgres-consumer'
. (Join-Path $PSScriptRoot 'test_pg_staging_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_deletion_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_process_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_lifecycle_lock_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_acl_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_consumer_lease_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_data_directory_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_runtime_identity_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_auth_contract.ps1')
