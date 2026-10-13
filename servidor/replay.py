"""Monta o clipe dos últimos N segundos a partir dos segmentos do buffer."""
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path


def listar_segmentos(pasta: Path) -> list[tuple[float, Path]]:
    segmentos = []
    for p in pasta.glob("*.ts"):
        try:
            inicio = datetime.strptime(p.stem, "%Y%m%d_%H%M%S").timestamp()
        except ValueError:
            continue
        segmentos.append((inicio, p))
    return sorted(segmentos)


def gerar_clip(pasta: Path, t_fim: float, duracao: int, segundos_segmento: int,
               saida: Path, thumb: Path, ffmpeg: str = "ffmpeg") -> float:
    """Gera `saida` (.mp4) com o intervalo [t_fim - duracao, t_fim]. Retorna a duração real."""
    # Espera o segmento que contém t_fim ser fechado, isto é, até surgir um segmento que começou depois dele.
    limite = time.time() + segundos_segmento * 4 + 5
    while True:
        segmentos = listar_segmentos(pasta)
        if segmentos and segmentos[-1][0] > t_fim:
            break
        if time.time() > limite:
            break
        time.sleep(0.5)

    fechados = segmentos[:-1]  # o último ainda está sendo escrito
    if not fechados:
        raise RuntimeError(f"sem vídeo no buffer de {pasta.name}")

    t_ini = t_fim - duracao
    escolhidos = []
    for i, (inicio, caminho) in enumerate(fechados):
        fim = segmentos[i + 1][0]
        if fim > t_ini and inicio < t_fim:
            escolhidos.append((inicio, caminho))
    if not escolhidos:
        raise RuntimeError(f"nenhum segmento cobre o replay em {pasta.name}")

    inicio_real = max(t_ini, escolhidos[0][0])
    deslocamento = inicio_real - escolhidos[0][0]
    duracao_real = t_fim - inicio_real

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as lista:
        for _, caminho in escolhidos:
            lista.write(f"file '{caminho.resolve().as_posix()}'\n")
    try:
        subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-ss", f"{deslocamento:.2f}", "-i", lista.name,
            "-t", f"{duracao_real:.2f}", "-c", "copy", "-movflags", "+faststart", str(saida),
        ], check=True, capture_output=True)
    finally:
        Path(lista.name).unlink(missing_ok=True)

    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-sseof", "-3", "-i", str(saida), "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(thumb),
    ], check=True, capture_output=True)
    return duracao_real
