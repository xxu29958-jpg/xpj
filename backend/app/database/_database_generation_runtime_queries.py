"""Fixed live PostgreSQL observations for installed generation admission."""

from sqlalchemy import text

LIVE_DATABASE_QUERY = text(
    """
    SELECT control.system_identifier::text, database.oid::bigint,
           current_database()::text,
           session_user::text,
           (SELECT dataset_id FROM public.dataset_authority WHERE singleton_id = 1),
           (SELECT restore_epoch FROM public.dataset_authority WHERE singleton_id = 1),
           (SELECT schema_revision FROM public.dataset_authority WHERE singleton_id = 1),
           (SELECT schema_min_compatible FROM public.dataset_authority WHERE singleton_id = 1),
           (SELECT semantic_revision FROM public.dataset_authority WHERE singleton_id = 1),
           COALESCE((
               SELECT pg_catalog.shobj_description(role.oid, 'pg_authid')
               FROM pg_catalog.pg_roles AS role
               WHERE role.rolname = 'postgres'
           ), ''),
           COALESCE((SELECT role.rolcanlogin AND role.rolinherit
                       AND NOT role.rolsuper AND NOT role.rolcreatedb
                       AND NOT role.rolcreaterole AND NOT role.rolreplication
                       AND NOT role.rolbypassrls AND role.rolconnlimit = -1
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = session_user
           ), false),
           COALESCE((SELECT COALESCE(role.rolconfig, ARRAY[]::text[]) =
                            ARRAY['search_path=pg_catalog, public']::text[]
                       AND NOT EXISTS (
                           SELECT 1 FROM pg_catalog.pg_db_role_setting AS setting
                           WHERE setting.setrole = role.oid
                             AND setting.setdatabase = database.oid
                       )
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = session_user
           ), false),
           NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_auth_members AS membership
               JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
              WHERE granted.rolname = session_user OR member.rolname = session_user
           ),
           COALESCE(pg_catalog.pg_get_userbyid(database.datdba) = 'ticketbox_owner', false),
           COALESCE((SELECT pg_catalog.pg_get_userbyid(namespace.nspowner) = 'ticketbox_owner'
                FROM pg_catalog.pg_namespace AS namespace WHERE namespace.nspname = 'public'
           ), false),
           pg_catalog.has_database_privilege(session_user, current_database(), 'CONNECT'),
           NOT pg_catalog.has_database_privilege(session_user, current_database(), 'CREATE'),
           NOT pg_catalog.has_database_privilege(session_user, current_database(), 'TEMPORARY'),
           pg_catalog.has_schema_privilege(session_user, 'public', 'USAGE'),
           NOT pg_catalog.has_schema_privilege(session_user, 'public', 'CREATE'),
           NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_class AS relation
               JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
              WHERE namespace.nspname = 'public'
                AND pg_catalog.pg_get_userbyid(relation.relowner) = session_user
               UNION ALL
               SELECT 1 FROM pg_catalog.pg_proc AS routine
               JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
              WHERE namespace.nspname = 'public'
                AND pg_catalog.pg_get_userbyid(routine.proowner) = session_user
               UNION ALL
               SELECT 1 FROM pg_catalog.pg_type AS type
               JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type.typnamespace
              WHERE namespace.nspname = 'public'
                AND pg_catalog.pg_get_userbyid(type.typowner) = session_user
           ),
           COALESCE((SELECT NOT role.rolcanlogin AND NOT role.rolinherit
                      AND NOT role.rolsuper AND NOT role.rolcreatedb
                      AND NOT role.rolcreaterole AND NOT role.rolreplication
                      AND NOT role.rolbypassrls AND role.rolconnlimit = -1
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = 'ticketbox_owner'
           ), false)
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_auth_members AS membership
               JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
               WHERE granted.rolname = 'ticketbox_owner' OR member.rolname = 'ticketbox_owner'
           ) AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_stat_activity WHERE usename = 'ticketbox_owner' AND pid <> pg_backend_pid()
           ),
           COALESCE((SELECT NOT role.rolcanlogin AND NOT role.rolinherit
                       AND NOT role.rolsuper AND NOT role.rolcreatedb
                       AND NOT role.rolcreaterole AND NOT role.rolreplication
                       AND NOT role.rolbypassrls AND role.rolconnlimit = 1
                       AND COALESCE(role.rolconfig, ARRAY[]::text[]) =
                           ARRAY['search_path=pg_catalog, public']::text[]
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = 'ticketbox_migrator'
           ), false)
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_db_role_setting AS setting
               JOIN pg_catalog.pg_roles AS role ON role.oid = setting.setrole
               WHERE role.rolname = 'ticketbox_migrator'
                 AND setting.setdatabase = database.oid
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_auth_members AS membership
               JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
               WHERE granted.rolname = 'ticketbox_migrator' OR member.rolname = 'ticketbox_migrator'
           ) AND NOT pg_catalog.has_database_privilege(
               'ticketbox_migrator', current_database(), 'CONNECT')
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_stat_activity WHERE usename = 'ticketbox_migrator' AND pid <> pg_backend_pid()
           ),
           COALESCE((SELECT role.rolcanlogin AND NOT role.rolinherit
                       AND NOT role.rolsuper AND NOT role.rolcreatedb
                       AND NOT role.rolcreaterole AND NOT role.rolreplication
                       AND NOT role.rolbypassrls AND role.rolconnlimit = 1
                       AND role.rolpassword IS NOT NULL
                       AND COALESCE(role.rolconfig, ARRAY[]::text[]) =
                           ARRAY['search_path=pg_catalog, public']::text[]
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = 'ticketbox_backup'
           ), false)
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_db_role_setting AS setting
               JOIN pg_catalog.pg_roles AS role ON role.oid = setting.setrole
               WHERE role.rolname = 'ticketbox_backup'
                 AND setting.setdatabase = database.oid
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_auth_members AS membership
               JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
               JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
               WHERE granted.rolname = 'ticketbox_backup'
                  OR member.rolname = 'ticketbox_backup'
           )
           AND pg_catalog.has_database_privilege(
               'ticketbox_backup', current_database(), 'CONNECT')
           AND NOT pg_catalog.has_database_privilege(
               'ticketbox_backup', current_database(), 'CREATE')
           AND NOT pg_catalog.has_database_privilege(
               'ticketbox_backup', current_database(), 'TEMPORARY')
           AND pg_catalog.has_schema_privilege('ticketbox_backup', 'public', 'USAGE')
           AND NOT pg_catalog.has_schema_privilege('ticketbox_backup', 'public', 'CREATE')
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_class AS relation
               JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
               WHERE namespace.nspname = 'public'
                 AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                 AND NOT pg_catalog.has_table_privilege('ticketbox_backup', relation.oid, 'SELECT')
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_class AS sequence
               JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = sequence.relnamespace
               WHERE namespace.nspname = 'public' AND sequence.relkind = 'S'
                 AND (NOT pg_catalog.has_sequence_privilege('ticketbox_backup', sequence.oid, 'SELECT')
                      OR pg_catalog.has_sequence_privilege('ticketbox_backup', sequence.oid, 'USAGE')
                      OR pg_catalog.has_sequence_privilege('ticketbox_backup', sequence.oid, 'UPDATE'))
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_proc AS routine
               JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
               WHERE namespace.nspname = 'public'
                 AND pg_catalog.has_function_privilege('ticketbox_backup', routine.oid, 'EXECUTE')
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_stat_activity
               WHERE usename = 'ticketbox_backup' AND pid <> pg_backend_pid()
           )
    FROM pg_catalog.pg_database AS database
    CROSS JOIN pg_catalog.pg_control_system() AS control
    WHERE database.datname = current_database()
    """
)

RUNTIME_ACL_EVIDENCE_QUERY = text(
    """
    WITH acl_rows AS (
        SELECT 'database'::text AS kind,
               database.datname AS object_name,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC') AS grantee,
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_database AS database,
             LATERAL pg_catalog.aclexplode(
                 COALESCE(database.datacl, pg_catalog.acldefault('d'::"char", database.datdba))
             ) AS acl
        WHERE database.datname = current_database()
        UNION ALL
        SELECT 'schema', namespace.nspname,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_namespace AS namespace,
             LATERAL pg_catalog.aclexplode(
                 COALESCE(namespace.nspacl, pg_catalog.acldefault('n'::"char", namespace.nspowner))
             ) AS acl
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT CASE WHEN relation.relkind = 'S' THEN 'sequence' ELSE 'relation' END,
               namespace.nspname || '.' || relation.relname,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                    relation.relowner
                )
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
        UNION ALL
        SELECT 'routine', namespace.nspname || '.' || routine.oid::regprocedure::text,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(routine.proacl, pg_catalog.acldefault('f'::"char", routine.proowner))
        ) AS acl
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 'routine', namespace.nspname || '.' || routine.oid::regprocedure::text,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(routine.proacl, pg_catalog.acldefault('f'::"char", routine.proowner))
        ) AS acl
        WHERE routine.oid = 'pg_catalog.pg_control_system()'::regprocedure
    )
    SELECT kind || E'\t' || object_name || E'\t' || grantee || E'\t' ||
           privilege_type || E'\t' || is_grantable::text
    FROM acl_rows
    WHERE NOT (
        kind = 'database'
        AND object_name = current_database()
        AND grantee IN ('ticketbox_runtime', 'ticketbox_migrator')
        AND privilege_type = 'CONNECT'
        AND NOT is_grantable
    )
    ORDER BY kind, object_name, grantee, privilege_type, is_grantable
    """
)

FRESH_DATASET_AUTHORITY_QUERY = text(
    """
    SELECT dataset_id, restore_epoch, schema_revision, schema_min_compatible,
           semantic_revision
    FROM public.dataset_authority
    WHERE singleton_id = 1
    """
)
