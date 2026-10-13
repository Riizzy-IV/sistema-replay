"""Envio dos clipes para o Supabase (Storage + tabela `replays`) com fila persistente em disco."""
import json
import logging
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

log = logging.getLogger("nuvem")


class Supabase:
    def __init__(self, url: str, chave_secreta: str, bucket: str):
        self.url = url.rstrip("/")
        self.bucket = bucket
        self.cabecalhos = {"apikey": chave_secreta}
        if chave_secreta.startswith("eyJ"):  # chave legada (JWT service_role)
            self.cabecalhos["Authorization"] = f"Bearer {chave_secreta}"
        self.http = httpx.Client(headers=self.cabecalhos, timeout=180)

    def enviar_arquivo(self, local: Path, remoto: str, tipo: str):
        r = self.http.post(f"{self.url}/storage/v1/object/{self.bucket}/{remoto}", content=local.read_bytes(),
                           headers={"Content-Type": tipo, "x-upsert": "true", "cache-control": "86400"})
        r.raise_for_status()

    def inserir_replay(self, linha: dict):
        r = self.http.post(f"{self.url}/rest/v1/replays", json=linha,
                           headers={"Prefer": "return=minimal,resolution=ignore-duplicates"})
        r.raise_for_status()

    def apagar_antigos(self, dias: int):
        corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
        r = self.http.get(f"{self.url}/rest/v1/replays",
                          params={"select": "video_path,thumb_path", "created_at": f"lt.{corte}"})
        r.raise_for_status()
        caminhos = [c for linha in r.json() for c in (linha["video_path"], linha["thumb_path"]) if c]
        if not caminhos:
            return
        for i in range(0, len(caminhos), 500):
            self.http.request("DELETE", f"{self.url}/storage/v1/object/{self.bucket}",
                              json={"prefixes": caminhos[i:i + 500]}).raise_for_status()
        self.http.delete(f"{self.url}/rest/v1/replays", params={"created_at": f"lt.{corte}"}).raise_for_status()
        log.info("removidos %d arquivos com mais de %d dias da nuvem", len(caminhos), dias)


class Enviador:
    """Lê `pendentes/*.json`, envia para a nuvem e move os arquivos para `clips/`.
    Se a internet cair, os arquivos ficam na fila e são reenviados depois."""

    def __init__(self, pendentes: Path, clips: Path, supabase: Supabase | None,
                 retencao_nuvem_dias: int, retencao_local_dias: int):
        self.pendentes = pendentes
        self.clips = clips
        self.supabase = supabase
        self.retencao_nuvem = retencao_nuvem_dias
        self.retencao_local = retencao_local_dias
        self._acordar = threading.Event()
        self._ultima_limpeza = 0.0
        self.erro: str | None = None

    def acordar(self):
        self._acordar.set()

    def fila(self) -> int:
        return len(list(self.pendentes.glob("*.json")))

    def _enviar(self, meta_arq: Path):
        meta = json.loads(meta_arq.read_text(encoding="utf-8"))
        video = meta_arq.with_suffix(".mp4")
        thumb = meta_arq.with_suffix(".jpg")
        if self.supabase:
            dia = meta["criado_em"][:10]
            remoto = f"{meta['quadra']}/{dia}/{meta['id']}"
            self.supabase.enviar_arquivo(video, f"{remoto}.mp4", "video/mp4")
            thumb_path = None
            if thumb.exists():
                self.supabase.enviar_arquivo(thumb, f"{remoto}.jpg", "image/jpeg")
                thumb_path = f"{remoto}.jpg"
            self.supabase.inserir_replay({
                "id": meta["id"], "replay_id": meta["replay_id"], "quadra": meta["quadra"],
                "camera": meta["camera"], "camera_nome": meta["camera_nome"],
                "created_at": meta["criado_em"], "duracao": meta["duracao"],
                "video_path": f"{remoto}.mp4", "thumb_path": thumb_path,
            })
        for arq in (video, thumb, meta_arq):
            if arq.exists():
                shutil.move(arq, self.clips / arq.name)
        log.info("replay %s %s", meta["id"], "enviado" if self.supabase else "salvo localmente")

    def _limpeza(self):
        if time.time() - self._ultima_limpeza < 3600:
            return
        self._ultima_limpeza = time.time()
        corte = time.time() - self.retencao_local * 86400
        for f in self.clips.iterdir():
            if f.stat().st_mtime < corte:
                f.unlink(missing_ok=True)
        if self.supabase:
            self.supabase.apagar_antigos(self.retencao_nuvem)

    def loop(self):
        while True:
            try:
                for meta_arq in sorted(self.pendentes.glob("*.json")):
                    self._enviar(meta_arq)
                self._limpeza()
                self.erro = None
                self._acordar.wait(300)
            except Exception as e:
                self.erro = str(e)
                log.warning("falha no envio, tentando de novo em 60s: %s", e)
                self._acordar.wait(60)
            self._acordar.clear()

    def iniciar(self):
        threading.Thread(target=self.loop, name="enviador", daemon=True).start()
