"""Gravação contínua de uma câmera em segmentos curtos (buffer circular em disco)."""
import logging
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger("gravador")

# Ajustes prontos por marca. No config.json basta {"modelo": "...", "ip": "...", "senha": "..."};
# qualquer campo informado na câmera (url, transporte, converter, usuario, porta) tem prioridade.
MODELOS = {
    # Intelbras/Dahua: configurar na câmera H.264 e I-frame = FPS; aí o vídeo é só copiado
    "intelbras": {"caminho": "/cam/realmonitor?channel=1&subtype=0", "transporte": "tcp", "converter": False},
    # Hikvision: idem, H.264 e I-frame = FPS
    "hikvision": {"caminho": "/Streaming/Channels/101", "transporte": "tcp", "converter": False},
    # Yoosee: só aceita UDP e transmite em H.265 sem opção de troca, por isso converte para H.264
    "yoosee": {"caminho": "/onvif1", "transporte": "udp", "converter": True},
}


def resolver_camera(cam: dict) -> dict:
    """Completa a câmera com os ajustes do modelo e monta a URL RTSP a partir de ip/usuario/senha."""
    modelo = cam.get("modelo")
    if not modelo:
        return cam
    if modelo not in MODELOS:
        raise ValueError(f"câmera {cam['id']}: modelo '{modelo}' desconhecido (use {', '.join(MODELOS)})")
    final = {**MODELOS[modelo], **cam}
    if "url" not in cam:
        usuario = quote(final.get("usuario", "admin"), safe="")
        senha = quote(final.get("senha", ""), safe="!$&'()*+,;=")
        final["url"] = f"rtsp://{usuario}:{senha}@{final['ip']}:{final.get('porta', 554)}{final['caminho']}"
    return final


class Gravador:
    def __init__(self, cam: dict, pasta_buffer: Path, pasta_logs: Path, segundos_segmento: int,
                 segundos_buffer: int, ffmpeg: str = "ffmpeg"):
        cam = resolver_camera(cam)
        self.cam = cam
        self.pasta = pasta_buffer / cam["id"]
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo_log = pasta_logs / f"{cam['id']}.log"
        self.seg = segundos_segmento
        self.buffer = segundos_buffer
        self.ffmpeg = ffmpeg
        self.proc: subprocess.Popen | None = None
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"gravador-{cam['id']}", daemon=True)

    def _comando(self) -> list[str]:
        url = self.cam["url"]
        video = ["-c:v", "copy"]
        if url.startswith("rtsp"):
            # -timeout (µs): se a câmera travar, o ffmpeg sai e o loop reinicia
            entrada = ["-rtsp_transport", self.cam.get("transporte", "tcp"), "-timeout", "10000000", "-i", url]
        elif url == "teste":
            # câmera simulada ao vivo, com relógio na tela (para testar sem câmera)
            relogio = ("drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':text='%{localtime}':"
                       "fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=16:x=(w-tw)/2:y=h-th-60")
            entrada = ["-re", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30,{relogio}",
                       "-f", "lavfi", "-i", "sine=frequency=440"]
            video = ["-c:v", "libx264", "-preset", "veryfast", "-g", "30", "-pix_fmt", "yuv420p"]
        elif url.startswith("webcam:"):
            # webcam USB (DirectShow). Ex.: "webcam:Logi Webcam C920e"; microfone opcional em "microfone"
            dispositivo = f"video={url.removeprefix('webcam:')}"
            if self.cam.get("microfone"):
                dispositivo += f":audio={self.cam['microfone']}"
            entrada = ["-f", "dshow", "-rtbufsize", "256M", "-vcodec", "mjpeg", "-video_size", "1920x1080",
                       "-framerate", "30", "-i", dispositivo]
            # webcam não entrega H.264: converte, com keyframe a cada 1s para o corte ficar preciso
            video = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "5M", "-bufsize", "10M",
                     "-pix_fmt", "yuv420p", "-force_key_frames", "expr:gte(t,n_forced*1)"]
        else:
            # arquivo de vídeo em loop, para testar sem câmera
            entrada = ["-re", "-stream_loop", "-1", "-i", url]
        if self.cam.get("converter"):
            # câmera em H.265 ou sem ajuste de GOP: converte para H.264 com keyframe a cada 1s
            video = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "5M", "-bufsize", "10M",
                     "-pix_fmt", "yuv420p", "-force_key_frames", "expr:gte(t,n_forced*1)"]
        audio_map = "1:a:0" if url == "teste" else "0:a:0?"
        return [
            self.ffmpeg, "-hide_banner", "-loglevel", "error", *entrada,
            "-map", "0:v:0", "-map", audio_map,
            *video, "-c:a", "aac", "-b:a", "96k",
            "-f", "segment", "-segment_time", str(self.seg), "-reset_timestamps", "1",
            "-strftime", "1", str(self.pasta / "%Y%m%d_%H%M%S.ts"),
        ]

    def idade_ultimo_segmento(self) -> float | None:
        arquivos = list(self.pasta.glob("*.ts"))
        if not arquivos:
            return None
        return time.time() - max(f.stat().st_mtime for f in arquivos)

    def _limpar_buffer(self):
        agora = time.time()
        for f in self.pasta.glob("*.ts"):
            try:
                if agora - f.stat().st_mtime > self.buffer:
                    f.unlink()
            except (FileNotFoundError, PermissionError):
                pass

    def _loop(self):
        espera = 2
        while not self._parar.is_set():
            inicio = time.time()
            log.info("[%s] iniciando gravação", self.cam["id"])
            with open(self.arquivo_log, "a", encoding="utf-8") as saida_log:
                self.proc = subprocess.Popen(self._comando(), stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=saida_log)
                while self.proc.poll() is None and not self._parar.is_set():
                    time.sleep(2)
                    self._limpar_buffer()
                    idade = self.idade_ultimo_segmento()
                    if time.time() - inicio > 20 and (idade is None or idade > max(10, self.seg * 5)):
                        log.warning("[%s] câmera parou de enviar vídeo, reiniciando", self.cam["id"])
                        self.proc.kill()
                if self.proc.poll() is None:
                    self.proc.kill()
                self.proc.wait()
            if self._parar.is_set():
                break
            # reinício com backoff se o ffmpeg cair logo de cara (câmera offline, senha errada...)
            espera = 2 if time.time() - inicio > 30 else min(espera * 2, 30)
            log.warning("[%s] ffmpeg saiu (código %s), tentando de novo em %ss — veja %s",
                        self.cam["id"], self.proc.returncode, espera, self.arquivo_log)
            self._parar.wait(espera)

    def iniciar(self):
        self._thread.start()

    def parar(self):
        self._parar.set()
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
