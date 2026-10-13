-- El Mare Replay — rode no Supabase: SQL Editor → New query → Run

create table if not exists public.replays (
  id          text primary key,            -- ex: quadra-1-20261013-183205-cam1
  replay_id   text not null,               -- agrupa os clipes das câmeras do mesmo apertão
  quadra      text not null,
  camera      text not null,
  camera_nome text,
  created_at  timestamptz not null default now(),
  duracao     int not null,
  video_path  text not null,
  thumb_path  text
);

create index if not exists replays_created_at_idx on public.replays (created_at desc);

-- O app lê com a chave pública (anon); só o PC da quadra (chave secreta) escreve.
alter table public.replays enable row level security;
drop policy if exists "replays leitura publica" on public.replays;
create policy "replays leitura publica" on public.replays for select to anon, authenticated using (true);

-- Novos replays aparecem no app na hora (Realtime)
alter publication supabase_realtime add table public.replays;

-- Bucket público para os vídeos e miniaturas
insert into storage.buckets (id, name, public)
values ('replays', 'replays', true)
on conflict (id) do nothing;
