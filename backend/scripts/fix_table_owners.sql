-- 2026-06-11 根因修复：06-04 PG cut-over 时整库由 postgres 超级用户灌入，
-- 47/50 张表 owner=postgres，应用用户 ticketbox 只有 DML 权限。cut-over 后
-- 第一个需要 ALTER 既有表的迁移（20260606_0001 / ADR-0043）被
-- 「必须是表 tags 的属主」拒绝 → backend 启动失败 → 生产自 06-07 静默停机。
-- 本脚本把 database / schema / 全部表 / 全部序列的 owner 归位到 ticketbox
--（应用用户即迁移执行者——其余 3 张表的现状），幂等可重跑。
-- ALTER SCHEMA 同时解决 PG 15+ 默认不授 public CREATE 的下一颗雷
--（0043 还要 CREATE TABLE 两张 undo 表）。
--
-- 用法（postgres 超级用户交互输密码，不留痕）：
--   & "C:\Program Files\PostgreSQL\17\bin\psql.exe" `
--       -U postgres -h 127.0.0.1 -d ticketbox -f backend\scripts\fix_table_owners.sql

ALTER DATABASE ticketbox OWNER TO ticketbox;
ALTER SCHEMA public OWNER TO ticketbox;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tableowner <> 'ticketbox'
  LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO ticketbox', r.tablename);
  END LOOP;

  FOR r IN
    SELECT sequencename FROM pg_sequences
    WHERE schemaname = 'public' AND sequenceowner <> 'ticketbox'
  LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO ticketbox', r.sequencename);
  END LOOP;

  FOR r IN
    SELECT viewname FROM pg_views
    WHERE schemaname = 'public' AND viewowner <> 'ticketbox'
  LOOP
    EXECUTE format('ALTER VIEW public.%I OWNER TO ticketbox', r.viewname);
  END LOOP;
END $$;

-- 自检：剩余错位对象应为 0 行
SELECT 'table' AS kind, tablename AS name, tableowner AS owner
FROM pg_tables WHERE schemaname = 'public' AND tableowner <> 'ticketbox'
UNION ALL
SELECT 'sequence', sequencename, sequenceowner
FROM pg_sequences WHERE schemaname = 'public' AND sequenceowner <> 'ticketbox';
