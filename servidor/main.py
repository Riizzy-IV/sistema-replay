"""Servidor de replay da quadra: grava as câmeras sem parar e gera o clipe quando o botão é apertado.

Rodar:  uvicorn main:app --host 0.0.0.0 --port 8000
"""
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from gravador import Gravador
from nuvem import Enviador, Supabase
from replay import gerar_clip

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("replay")

BASE = Path(__file__).parent
cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
FFMPEG = cfg.get("ffmpeg", "ffmpeg")
DADOS = BASE / cfg.get("pasta_dados", "dados")
BUFFER, PENDENTES, CLIPS, LOGS = DADOS / "buffer", DADOS / "pendentes", DADOS / "clips", DADOS / "logs"
for pasta in (BUFFER, PENDENTES, CLIPS, LOGS):
    pasta.mkdir(parents=True, exist_ok=True)

sb_cfg = cfg.get("supabase", {})
supabase = Supabase(sb_cfg["url"], sb_cfg["chave_secreta"], sb_cfg.get("bucket", "replays")) \
    if sb_cfg.get("url") and sb_cfg.get("chave_secreta") else None
enviador = Enviador(PENDENTES, CLIPS, supabase, sb_cfg.get("retencao_dias", 7), cfg.get("retencao_local_dias", 3))
gravadores = [Gravador(cam, BUFFER, LOGS, cfg["segundos_segmento"], cfg["segundos_buffer"], FFMPEG)
              for cam in cfg["cameras"]]

_trava = threading.Lock()
_ultimo_replay = 0.0
_recentes: list[dict] = []


def processar(replay_id: str, t_fim: float):
    criado_em = datetime.fromtimestamp(t_fim, timezone.utc).isoformat()

    def uma_camera(g: Gravador):
        cam = g.cam
        base = PENDENTES / f"{replay_id}-{cam['id']}"
        try:
            duracao = gerar_clip(g.pasta, t_fim, cfg["segundos_replay"], cfg["segundos_segmento"],
                                 base.with_suffix(".mp4"), base.with_suffix(".jpg"), FFMPEG)
            meta = {"id": base.name, "replay_id": replay_id, "quadra": cfg["quadra"], "camera": cam["id"],
                    "camera_nome": cam.get("nome", cam["id"]), "criado_em": criado_em, "duracao": round(duracao)}
            # o .json é escrito por último: ele marca o clipe como pronto para envio
            base.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            _recentes.insert(0, {**meta, "status": "ok"})
        except Exception as e:
            log.exception("falha ao gerar replay %s da câmera %s", replay_id, cam["id"])
            _recentes.insert(0, {"id": base.name, "status": f"erro: {e}"})
        del _recentes[20:]

    threads = [threading.Thread(target=uma_camera, args=(g,)) for g in gravadores]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    enviador.acordar()


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    for g in gravadores:
        g.iniciar()
    enviador.iniciar()
    yield
    for g in gravadores:
        g.parar()


app = FastAPI(title="El Mare Replay", lifespan=ciclo_de_vida)


@app.post("/replay", status_code=202)
def criar_replay(x_token: str | None = Header(None), token: str | None = None):
    global _ultimo_replay
    if (x_token or token) != cfg["token"]:
        raise HTTPException(401, "token inválido")
    with _trava:
        agora = time.time()
        if agora - _ultimo_replay < cfg["cooldown_segundos"]:
            raise HTTPException(429, "replay já está sendo gerado")
        _ultimo_replay = agora
    replay_id = f"{cfg['quadra']}-{datetime.fromtimestamp(agora):%Y%m%d-%H%M%S}"
    log.info("botão apertado → %s", replay_id)
    threading.Thread(target=processar, args=(replay_id, agora), daemon=True).start()
    return {"id": replay_id}


@app.get("/status")
def status():
    return {
        "quadra": cfg["quadra"],
        "cameras": [{"id": g.cam["id"], "nome": g.cam.get("nome"),
                     "segundos_desde_ultimo_video": None if (i := g.idade_ultimo_segmento()) is None else round(i, 1)}
                    for g in gravadores],
        "nuvem": "supabase" if supabase else "desligada (só local)",
        "fila_envio": enviador.fila(),
        "erro_envio": enviador.erro,
        "recentes": _recentes,
    }


@app.get("/api/replays")
def listar_replays(de: str, ate: str):
    """Modo local: o app lê os replays direto do PC (quando não há Supabase ou sem internet)."""
    inicio, fim = datetime.fromisoformat(de.replace("Z", "+00:00")), datetime.fromisoformat(ate.replace("Z", "+00:00"))
    linhas = []
    for meta_arq in CLIPS.glob("*.json"):
        m = json.loads(meta_arq.read_text(encoding="utf-8"))
        if inicio <= datetime.fromisoformat(m["criado_em"]) < fim:
            thumb = meta_arq.with_suffix(".jpg")
            linhas.append({"id": m["id"], "replay_id": m["replay_id"], "quadra": m["quadra"], "camera": m["camera"],
                           "camera_nome": m["camera_nome"], "created_at": m["criado_em"], "duracao": m["duracao"],
                           "video_path": f"{m['id']}.mp4", "thumb_path": thumb.name if thumb.exists() else None})
    return sorted(linhas, key=lambda l: l["created_at"], reverse=True)


@app.delete("/replays")
def apagar_replays(request: Request):
    """Apaga todos os replays locais (botão do painel; só no próprio PC)."""
    if request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "só no PC da quadra")
    arquivos = [f for pasta in (CLIPS, PENDENTES) for f in pasta.iterdir() if f.is_file()]
    for f in arquivos:
        f.unlink(missing_ok=True)
    _recentes.clear()
    return {"apagados": sum(f.suffix == ".mp4" for f in arquivos)}


@app.get("/botao", response_class=HTMLResponse)
def botao():
    """Botão virtual para o celular (substitui o botão físico em testes). Abrir com /botao?t=TOKEN."""
    return (BASE / "botao.html").read_text(encoding="utf-8")


app.mount("/midia", StaticFiles(directory=CLIPS), name="midia")
app.mount("/app", StaticFiles(directory=BASE.parent / "app", html=True), name="app")


@app.get("/", response_class=HTMLResponse)
def painel(request: Request):
    # painel de teste: só abre no próprio PC, porque leva o token embutido
    if request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "painel disponível só no PC da quadra")
    return (BASE / "painel.html").read_text(encoding="utf-8").replace("{{TOKEN}}", cfg["token"])
