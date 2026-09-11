#!/usr/bin/tclsh

set superpass [expr {[info exists env(PG_SUPERUSER_PASSWORD)] ? $env(PG_SUPERUSER_PASSWORD) : "standpass"}]
set apppass [expr {[info exists env(APP_PASSWORD)]? $env(APP_PASSWORD) : "apppass"}]

dbset db  pg
dbset bm  TPROC-C

diset connection pg_host 127.0.0.1
diset connection pg_port 5432

diset tpcc pg_count_ware 100
diset tpcc pg_num_vu 4
diset tpcc pg_superuser postgres
diset tpcc pg_superuserpass $superpass
diset tpcc pg_defaultdbase postgres
diset tpcc pg_user app
diset tpcc pg_pass $apppass
diset tpcc pg_dbase bench
diset tpcc pg_partition false

print dict
buildschema