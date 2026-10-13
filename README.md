# El Mare Replay

Botão na quadra → salva os **últimos 20 segundos** de vídeo → aparece no app dos jogadores.

```
Câmera(s) IP ──RTSP──► PC Windows (servidor/) ──upload──► Supabase ──► App PWA (app/)
                           ▲
              Botão ESP32 (esp32-botao/) via Wi-Fi
```

| Pasta | O que é |
|---|---|
| `servidor/` | Roda no PC da quadra. Grava as câmeras sem parar em pedaços de 2s (mantém só os últimos 3 min), gera o clipe quando o botão é apertado e envia para a nuvem. |
| `app/` | App web instalável (PWA) que os jogadores abrem no celular. Lista os replays do dia, toca, baixa e compartilha. |
| `supabase/` | Script do banco de dados e do storage. |
| `esp32-botao/` | Firmware do botão físico. |

---

## 1. Câmera

Na configuração da câmera (pelo navegador, no IP dela):

- **Codec: H.264** (não H.265: o H.265 não toca na maioria dos celulares e navegadores).
- **Resolução 1080p, 25 ou 30 fps, bitrate 3–4 Mbps.** Um clipe de 20s fica com uns 9 MB.
- **Intervalo de I-frame (GOP) = mesmo valor do FPS** (ex.: 30). Isso deixa o corte preciso, com menos de 1s de erro.
- Anote a URL RTSP. Exemplos:
  - Intelbras/Dahua: `rtsp://admin:SENHA@IP:554/cam/realmonitor?channel=1&subtype=0`
  - Hikvision: `rtsp://admin:SENHA@IP:554/Streaming/Channels/101`
  - Reolink: `rtsp://admin:SENHA@IP:554/h264Preview_01_main`

Teste a URL no VLC (Mídia → Abrir fluxo de rede) antes de seguir.

**1 ou 2 câmeras:** basta adicionar a segunda em `cameras` no `config.json`. Cada apertão gera um clipe por câmera, e o app mostra abas "Fundo / Lateral".

## 2. Supabase (nuvem)

1. Crie um projeto em [supabase.com](https://supabase.com).
2. **SQL Editor** → cole o conteúdo de `supabase/schema.sql` → **Run**.
3. Em **Project Settings → API Keys**, copie:
   - a **URL** do projeto;
   - a **chave pública** (anon/publishable), que vai no app;
   - a **chave secreta** (secret/service_role), que vai **só** no `config.json` do PC.

> **Espaço:** o plano grátis tem 1 GB, o que dá uns 60 clipes. O servidor apaga sozinho os replays mais antigos que `retencao_dias`. Com movimento grande, o plano Pro (US$ 25/mês, 100 GB) aguenta 7 dias com folga.

## 3. PC da quadra (Windows)

1. Instale o Python e o FFmpeg (PowerShell):
   ```powershell
   winget install Python.Python.3.13
   winget install Gyan.FFmpeg
   ```
2. Copie `servidor/config.example.json` para `servidor/config.json` e preencha:
   - `token`: uma senha longa qualquer (a mesma vai no ESP32);
   - `cameras`: URL RTSP de cada câmera;
   - `supabase`: URL e chave secreta. Deixe a `url` vazia para testar só local.
3. Rode `servidor\iniciar.bat`. Na primeira vez ele instala tudo.
4. Abra **http://localhost:8000** no PC. É o painel de teste, com o botão "Gerar replay" e o status das câmeras.

**Para deixar 24h ligado:**
- Configure um **IP fixo** para o PC (no roteador, por reserva de DHCP).
- Libere a porta no firewall (PowerShell como administrador):
  ```powershell
  netsh advfirewall firewall add rule name="El Mare Replay" dir=in action=allow protocol=TCP localport=8000
  ```
- **Energia:** Configurações → Energia → Suspensão = **Nunca**.
- **Iniciar sozinho:** Agendador de Tarefas → Criar tarefa → Disparador "Ao iniciar o sistema" → Ação: `servidor\iniciar.bat` → marque "Executar estando o usuário conectado ou não".

**Testar sem câmera:** em `url`, coloque o caminho de um arquivo `.mp4` (ex.: `C:/videos/teste.mp4`). Ele toca em loop como se fosse a câmera.

### API

| Rota | Uso |
|---|---|
| `POST /replay` (header `X-Token`) | Gera um replay. Responde `202` (ok), `429` (já está gerando) ou `401` (token errado). |
| `GET /status` | Estado das câmeras, fila de envio e últimos replays. |
| `GET /` | Painel de teste (só abre no próprio PC). |

Se a internet cair, os clipes ficam em `servidor/dados/pendentes/` e são enviados quando ela voltar. Os logs do ffmpeg de cada câmera ficam em `servidor/dados/logs/`.

## 4. App (PWA)

1. Preencha `app/config.js` com a URL e a **chave pública** do Supabase.
2. Publique a pasta `app/` num host com HTTPS. O mais simples é o [Netlify Drop](https://app.netlify.com/drop) (arrastar a pasta) ou o Cloudflare Pages / Vercel.
3. Para o jogador instalar: abrir o link no celular → **"Adicionar à tela inicial"**. Vale colocar um QR code com o link do app na quadra.

Os novos replays aparecem no app sozinhos, sem recarregar a página.

## 5. Botão (ESP32)

**Material:** ESP32 DevKit, botão arcade de 60 mm, caixa estanque IP65 e fonte 5V USB.

1. Ligue um terminal do botão no **GPIO 13** e o outro no **GND**.
2. Arduino IDE → instale a placa "esp32" (Espressif) → abra `esp32-botao/esp32-botao.ino`.
3. Preencha Wi-Fi, o IP do PC e o token → placa **ESP32 Dev Module** → Upload.

O LED da placa mostra o resultado: 3 piscadas = salvo; piscada longa = aguarde; piscando rápido = erro.

---

## Observações

- **LGPD:** os vídeos ficam num bucket público. Quem tiver o app vê os replays de todos. Coloque um aviso de filmagem visível na quadra. Se quiser restringir depois, dá para filtrar por reserva/horário.
- **Logo/marca d'água no vídeo:** é possível, mas exige recodificar o clipe (leva uns 10s a mais por replay).
