# Guía de Setup — cordada-ceo-agents

Paso a paso para dejar todo funcionando. Asume que partes de cero.

---

## Paso 1 — Verificar Python

Abre la Terminal (Mac: busca "Terminal" en Spotlight).

```bash
python3 --version
```

Si ves algo como `Python 3.11.x` o superior, sigue al Paso 2.

Si no, instala Python:

**Mac:**
```bash
# Instala Homebrew si no lo tienes
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Instala Python
brew install python
```

**Windows:**
Descarga desde https://www.python.org/downloads/ e instala. Marca "Add Python to PATH" durante la instalación.

Verifica de nuevo:
```bash
python3 --version
```

---

## Paso 2 — Clonar el repositorio

```bash
# Ve a tu carpeta de proyectos (o donde quieras tenerlo)
cd ~/Documents

# Clona el repo (reemplaza YOUR_USERNAME con tu usuario de GitHub)
git clone git@github.com:YOUR_USERNAME/cordada-ceo-agents.git

# Entra al repo
cd cordada-ceo-agents
```

Si git te pide autenticación, necesitas configurar SSH keys:
https://docs.github.com/en/authentication/connecting-to-github-with-ssh

Alternativa sin SSH:
```bash
git clone https://github.com/YOUR_USERNAME/cordada-ceo-agents.git
```

---

## Paso 3 — Crear entorno virtual

Esto aísla las dependencias de este proyecto del resto de tu sistema.

```bash
python3 -m venv venv
source venv/bin/activate   # Mac/Linux
# venv\Scripts\activate    # Windows
```

Deberías ver `(venv)` al inicio de tu línea de terminal.

---

## Paso 4 — Instalar dependencias

```bash
pip install -r requirements.txt
```

---

## Paso 5 — Obtener API key de Anthropic

1. Ve a https://console.anthropic.com/
2. Crea una cuenta si no tienes
3. Ve a "API Keys" en el menú
4. Crea una nueva key
5. Copia la key (empieza con `sk-ant-...`)

**Importante:** Anthropic cobra por uso de API. El modelo `claude-sonnet-4-20250514` cuesta aproximadamente $3/millón de tokens de input y $15/millón de tokens de output. Un pipeline completo (9 agentes) cuesta entre $0.50 y $3.00 USD dependiendo del largo de los documentos.

---

## Paso 6 — Configurar API key

```bash
cp .env.example .env
```

Edita el archivo `.env` con cualquier editor de texto:
```bash
nano .env   # o abre con tu editor preferido
```

Pega tu API key:
```
ANTHROPIC_API_KEY=sk-ant-tu-key-aqui
```

Guarda y cierra (en nano: Ctrl+X, luego Y, luego Enter).

---

## Paso 7 — Verificar que todo funciona

```bash
python -m orchestrator.agent_runner --agent discover --input "test de conexión"
```

Si ves la respuesta de Claude, todo está configurado. Si ves un error, revisa:
- ¿Tu API key es correcta?
- ¿Activaste el entorno virtual (`source venv/bin/activate`)?
- ¿Instalaste las dependencias (`pip install -r requirements.txt`)?

---

## Uso diario

Cada vez que quieras usar los agentes:

```bash
# 1. Abre terminal
# 2. Ve al repo
cd ~/Documents/cordada-ceo-agents

# 3. Activa el entorno virtual
source venv/bin/activate

# 4. Corre lo que necesites
python -m orchestrator.agent_runner --agent compile --input "tu input aquí"
```

---

## Comandos útiles

```bash
# Correr un agente específico
python -m orchestrator.agent_runner --agent discover --input "tema"
python -m orchestrator.agent_runner --agent compile --input-file ./mis_notas.md

# Correr pipeline completo
python -m orchestrator.pipeline --topic "tema de investigación"

# Correr desde una etapa específica
python -m orchestrator.pipeline --from compile --input-file ./outputs/validated.md

# Ver ayuda
python -m orchestrator.agent_runner --help
python -m orchestrator.pipeline --help
```

---

## Troubleshooting

**"command not found: python3"**
→ Python no está instalado. Ve al Paso 1.

**"No module named 'anthropic'"**
→ No instalaste las dependencias. Corre `pip install -r requirements.txt`.

**"AuthenticationError"**
→ Tu API key es incorrecta o expiró. Verifica en https://console.anthropic.com/

**"RateLimitError"**
→ Estás enviando muchas requests. Espera unos segundos y reintenta.

**El entorno virtual no se activa**
→ Asegúrate de estar en la carpeta del repo y corre `source venv/bin/activate` de nuevo.
