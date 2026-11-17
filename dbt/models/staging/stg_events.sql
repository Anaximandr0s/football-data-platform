-- replay_id says which Bronze replay Silver read; not part of Gold
select * exclude (replay_id) from {{ silver_table('events') }}
