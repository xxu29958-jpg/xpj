#Requires -Version 5.1

function New-TicketboxPostgresqlWriterFenceSessionDrainSql {
    param(
        [Parameter(Mandatory = $true)][string]$ManagedRolesSql,
        [ValidateRange(1, 3600000)]
        [int]$TerminationTimeoutMilliseconds
    )

    return @"
DO `$writer_fence`$
DECLARE fence_pid integer;
BEGIN
    LOOP
        PERFORM pg_stat_clear_snapshot();
        FOR fence_pid IN
            SELECT DISTINCT candidate.pid
            FROM (
                SELECT activity.pid
                FROM pg_stat_activity AS activity
                WHERE activity.datid = (
                    SELECT oid FROM pg_database
                    WHERE datname = current_database()
                )
                  AND activity.pid <> pg_backend_pid()
                  AND activity.backend_type = 'client backend'
                  AND activity.usename = ANY($ManagedRolesSql)
                UNION
                SELECT database_lock.pid
                FROM pg_locks AS database_lock
                WHERE database_lock.pid IS NOT NULL
                  AND database_lock.pid <> pg_backend_pid()
                  AND database_lock.locktype = 'object'
                  AND database_lock.mode = 'RowExclusiveLock'
                  AND database_lock.classid = 'pg_database'::regclass::oid
                  AND database_lock.objid = (
                      SELECT oid FROM pg_database
                      WHERE datname = current_database()
                  )
                  AND database_lock.objsubid = 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pg_stat_activity AS visible_activity
                      WHERE visible_activity.pid = database_lock.pid
                  )
            ) AS candidate
        LOOP
            IF NOT pg_terminate_backend(
                fence_pid,
                $TerminationTimeoutMilliseconds
            ) THEN
                PERFORM pg_stat_clear_snapshot();
                IF EXISTS (
                    SELECT 1
                    FROM pg_stat_activity AS activity
                    WHERE activity.pid = fence_pid
                      AND activity.datid = (
                          SELECT oid FROM pg_database
                          WHERE datname = current_database()
                      )
                      AND activity.backend_type = 'client backend'
                      AND activity.usename = ANY($ManagedRolesSql)
                    UNION ALL
                    SELECT 1
                    FROM pg_locks AS database_lock
                    WHERE database_lock.pid = fence_pid
                      AND database_lock.locktype = 'object'
                      AND database_lock.mode = 'RowExclusiveLock'
                      AND database_lock.classid = 'pg_database'::regclass::oid
                      AND database_lock.objid = (
                          SELECT oid FROM pg_database
                          WHERE datname = current_database()
                      )
                      AND database_lock.objsubid = 0
                      AND NOT EXISTS (
                          SELECT 1
                          FROM pg_stat_activity AS visible_activity
                          WHERE visible_activity.pid = database_lock.pid
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Target-database client or startup backend did not terminate';
                END IF;
            END IF;
        END LOOP;
        PERFORM pg_stat_clear_snapshot();
        EXIT WHEN NOT EXISTS (
            SELECT 1
            FROM pg_stat_activity AS activity
            WHERE activity.datid = (
                SELECT oid FROM pg_database
                WHERE datname = current_database()
            )
              AND activity.pid <> pg_backend_pid()
              AND activity.backend_type = 'client backend'
              AND activity.usename = ANY($ManagedRolesSql)
        ) AND NOT EXISTS (
            SELECT 1
            FROM pg_locks AS database_lock
            WHERE database_lock.pid IS NOT NULL
              AND database_lock.pid <> pg_backend_pid()
              AND database_lock.locktype = 'object'
              AND database_lock.mode = 'RowExclusiveLock'
              AND database_lock.classid = 'pg_database'::regclass::oid
              AND database_lock.objid = (
                  SELECT oid FROM pg_database
                  WHERE datname = current_database()
              )
              AND database_lock.objsubid = 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_stat_activity AS visible_activity
                  WHERE visible_activity.pid = database_lock.pid
              )
        );
    END LOOP;
END
`$writer_fence`$;
"@
}
