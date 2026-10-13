/*
  El Mare Replay — botão da quadra (ESP32)

  Ligações:
    - Botão arcade: um terminal no GPIO 13, o outro no GND (usa o pull-up interno)
    - LED: GPIO 2 (LED azul da própria placa) ou um LED externo com resistor de 220Ω

  LED:
    - piscando devagar  → conectando no Wi-Fi
    - 3 piscadas        → replay salvo
    - 1 piscada longa   → replay já estava sendo gerado (aguarde uns segundos)
    - piscando rápido   → erro (PC desligado, token errado...)

  Gravar: Arduino IDE → placa "ESP32 Dev Module" → Upload
*/
#include <WiFi.h>
#include <HTTPClient.h>

// ======== CONFIGURE AQUI ========
const char* WIFI_NOME  = "NOME_DO_WIFI";
const char* WIFI_SENHA = "SENHA_DO_WIFI";
const char* SERVIDOR   = "http://192.168.1.10:8000/replay";  // IP fixo do PC da quadra
const char* TOKEN      = "TROQUE-POR-UMA-SENHA-LONGA";       // o mesmo do config.json
// ================================

const int PINO_BOTAO = 13;
const int PINO_LED = 2;

void piscar(int vezes, int ms) {
  for (int i = 0; i < vezes; i++) {
    digitalWrite(PINO_LED, HIGH); delay(ms);
    digitalWrite(PINO_LED, LOW);  delay(ms);
  }
}

void conectarWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_NOME, WIFI_SENHA);
  Serial.print("Conectando no Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    piscar(1, 400);
    Serial.print(".");
  }
  Serial.printf("\nConectado: %s\n", WiFi.localIP().toString().c_str());
}

void pedirReplay() {
  digitalWrite(PINO_LED, HIGH);
  HTTPClient http;
  http.begin(SERVIDOR);
  http.setTimeout(5000);
  http.addHeader("X-Token", TOKEN);
  int codigo = http.POST("");
  http.end();
  digitalWrite(PINO_LED, LOW);
  Serial.printf("Replay: HTTP %d\n", codigo);

  if (codigo == 202)      piscar(3, 150);
  else if (codigo == 429) piscar(1, 800);
  else                    piscar(15, 60);
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_BOTAO, INPUT_PULLUP);
  pinMode(PINO_LED, OUTPUT);
  conectarWifi();
}

void loop() {
  conectarWifi();
  if (digitalRead(PINO_BOTAO) == LOW) {
    delay(40);  // debounce
    if (digitalRead(PINO_BOTAO) == LOW) {
      pedirReplay();
      while (digitalRead(PINO_BOTAO) == LOW) delay(10);  // espera soltar
    }
  }
  delay(10);
}
