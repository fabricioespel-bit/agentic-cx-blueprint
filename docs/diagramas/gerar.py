"""Gera os 4 diagramas do documento como SVG (fonte versionável).

Uso: python gerar.py  (sem dependências). Saída: diagrama-1.svg ... diagrama-4.svg.
Largura lógica 900 = 180 mm no PDF (5 unidades por mm).
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent

STYLE = """
<style>
  text { font-family: -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif; fill: #1f2937; }
  .t { font-size: 12.5px; font-weight: 600; }
  .s { font-size: 11px; fill: #374151; }
  .l { font-size: 10.5px; fill: #374151; paint-order: stroke; stroke: #fff; stroke-width: 4px; }
  .b { font-size: 11px; font-weight: 600; fill: #4b5563; }
  .new { fill: #e8f0fb; stroke: #1f5fae; stroke-width: 1.4; }
  .llm { fill: #f1eafb; stroke: #6b3fa0; stroke-width: 1.4; }
  .exist { fill: #eef0f3; stroke: #8a8f98; stroke-width: 1.2; stroke-dasharray: 4 3; }
  .ext { fill: #ffffff; stroke: #4b5563; stroke-width: 1.2; }
  .person { fill: #fff7e6; stroke: #b7791f; stroke-width: 1.2; }
  .bound { fill: none; stroke: #6b7280; stroke-width: 1.2; stroke-dasharray: 6 4; }
  .a { fill: none; stroke: #4b5563; stroke-width: 1.2; }
  .ad { fill: none; stroke: #4b5563; stroke-width: 1.2; stroke-dasharray: 4 3; }
  .life { stroke: #9ca3af; stroke-width: 1; stroke-dasharray: 3 3; }
</style>
<defs>
  <marker id="m" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#4b5563"/>
  </marker>
</defs>
"""


class Svg:
    def __init__(self, h: int):
        self.h = h
        self.parts: list[str] = []

    def box(self, x, y, w, h, lines, kind="new", rx=6):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" class="{kind}"/>')
        lh = 14
        y0 = y + h / 2 - (len(lines) - 1) * lh / 2 + 4
        for i, line in enumerate(lines):
            cls = "t" if i == 0 else "s"
            self.parts.append(
                f'<text x="{x + w / 2}" y="{y0 + i * lh}" text-anchor="middle" class="{cls}">{escape(line)}</text>'
            )

    def bound(self, x, y, w, h, label):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" class="bound"/>')
        self.parts.append(f'<text x="{x + 10}" y="{y + 15}" class="b">{escape(label)}</text>')

    def arrow(self, pts, label=None, at=None, dashed=False, both=False, anchor="middle", rotate=None):
        d = " ".join(f"{x},{y}" for x, y in pts)
        start = ' marker-start="url(#m)"' if both else ""
        cls = "ad" if dashed else "a"
        self.parts.append(f'<polyline points="{d}" class="{cls}" marker-end="url(#m)"{start}/>')
        if label:
            lx, ly = at
            tr = f' transform="rotate({rotate} {lx} {ly})"' if rotate else ""
            self.parts.append(
                f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" class="l"{tr}>{escape(label)}</text>'
            )

    def text(self, x, y, s, cls="s", anchor="start"):
        self.parts.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" class="{cls}">{escape(s)}</text>')

    def raw(self, s):
        self.parts.append(s)

    def save(self, name):
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {self.h}" width="100%">'
            f"{STYLE}{''.join(self.parts)}</svg>"
        )
        (OUT / name).write_text(svg, encoding="utf-8")


def legenda(s: Svg, x, y, itens):
    for kind, label in itens:
        s.raw(f'<rect x="{x}" y="{y - 9}" width="14" height="10" rx="2" class="{kind}"/>')
        s.text(x + 19, y, label)
        x += 19 + len(label) * 6 + 18


def contexto():
    s = Svg(362)
    legenda(s, 330, 22, [("new", "novo (escopo)"), ("exist", "existente"), ("ext", "externo"), ("person", "pessoa")])
    s.box(50, 8, 150, 40, ["Cliente"], "person", rx=18)
    s.box(50, 85, 190, 50, ["App do banco", "canal + fator de autenticação"], "exist")
    s.box(260, 85, 220, 50, ["WhatsApp", "Meta + provedor"], "ext")
    s.box(720, 85, 140, 50, ["Atendente humano"], "person", rx=18)
    s.bound(50, 160, 630, 95, "Plataforma de atendimento")
    s.box(70, 185, 240, 55, ["Atendimento existente", "preservado"], "exist")
    s.box(340, 185, 320, 55, ["Camada agêntica (nova)", "assistente + blueprint replicável"], "new")
    s.box(720, 185, 140, 55, ["CRM / atendimento", "handoff, fila, protocolo"], "ext")
    bottom = [
        ["Provedor de identidade", "token e nível"],
        ["Sistemas de cartões", "+ antifraude (via APIs)"],
        ["Barramento de eventos", "CRM, antifraude, notificação"],
        ["Plataforma de IA", "Gemini, global", "sem identificadores"],
        ["Monitoramento", "corporativo + auditoria"],
    ]
    for i, lines in enumerate(bottom):
        s.box(40 + i * 166, 295, 156, 60, lines, "ext")
    s.arrow([(125, 48), (125, 85)])
    s.arrow([(170, 48), (170, 66), (370, 66), (370, 85)], "conversa", (270, 62))
    s.arrow([(145, 135), (145, 160)])
    s.arrow([(370, 135), (370, 160)])
    for cx in (118, 284, 450, 616):
        s.arrow([(cx, 255), (cx, 295)])
    s.arrow([(680, 245), (700, 245), (700, 275), (782, 275), (782, 295)])
    s.arrow([(680, 212), (720, 212)])
    s.arrow([(790, 135), (790, 185)])
    s.arrow([(50, 110), (25, 110), (25, 325), (40, 325)], "vínculo e step-up", (20, 218), dashed=True, rotate=-90)
    s.save("diagrama-1.svg")


def containers():
    s = Svg(480)
    s.box(40, 8, 200, 40, ["WhatsApp (Meta + provedor)"], "ext")
    s.box(255, 8, 140, 40, ["App do banco"], "exist")
    s.box(440, 8, 200, 40, ["Plataforma de IA (Gemini)", "global · sem identificadores"], "ext")
    s.bound(20, 65, 860, 330, "Plataforma de atendimento")
    s.box(40, 90, 300, 58, ["① Gateway de canal · Cloud Run", "dedup, identidade, mascaramento (SDP, SP),", "roteador, botões, placeholders"])
    s.box(600, 90, 260, 58, ["Atendimento existente", "bot ou fluxo legado"], "exist")
    s.box(40, 175, 220, 58, ["⑥ Cofre de sessão · Firestore SP", "token + dados reais · expira", "IAM: só gateway e MCP"])
    s.box(300, 175, 260, 58, ["② Agente · ADK no Agent Runtime", "grafo com LLM nos nós", "um por área de negócio"])
    s.box(600, 175, 260, 58, ["⑧ Guardrails gerenciados", "Model Armor (EUA),", "sobre texto pseudonimizado"])
    s.box(40, 260, 200, 58, ["③ Política · Cloud Run", "catálogo assinado + piso", "confirmação amarrada"])
    s.box(260, 260, 200, 58, ["④ Conhecimento", "RAG Engine SP + ingestão", "cache semântico"])
    s.box(480, 260, 200, 58, ["⑤ Servidores MCP · Cloud Run", "um por domínio de sistema", "em nome do cliente"])
    s.box(40, 335, 420, 45, ["⑨ Auditoria (imutável) · Observabilidade (OTel) · Avaliação", "todos os containers emitem traces e auditoria"])
    s.box(700, 335, 160, 45, ["⑦ Registro de execuções", "idempotência + outbox"])
    s.box(40, 420, 180, 50, ["Provedor de identidade"], "ext")
    s.box(230, 420, 200, 50, ["Monitoramento corporativo", "(ex.: Dynatrace)"], "ext")
    s.box(480, 420, 200, 50, ["Sistemas do banco", "cartões, tarifas, CRM, antifraude"], "ext")
    s.box(700, 420, 160, 50, ["Barramento de eventos"], "ext")
    s.arrow([(140, 48), (140, 90)])
    s.arrow([(325, 48), (325, 90)])
    s.arrow([(340, 119), (600, 119)], "intenções não migradas", (440, 113))
    s.arrow([(520, 175), (520, 48)], "texto pseudonimizado", (526, 82), anchor="start")
    s.arrow([(320, 148), (320, 175)], "mensagem mascarada", (326, 166), anchor="start")
    s.arrow([(150, 148), (150, 175)], both=True)
    s.arrow([(560, 204), (600, 204)], both=True)
    s.arrow([(330, 233), (330, 246), (140, 246), (140, 260)], "pré-check", (235, 243))
    s.arrow([(400, 233), (400, 260)])
    s.arrow([(530, 233), (530, 260)], "ferramentas", (536, 252), anchor="start")
    s.arrow([(500, 318), (500, 327), (170, 327), (170, 318)], "aplica a política", (335, 331))
    s.arrow([(680, 289), (780, 289), (780, 335)])
    s.arrow([(780, 380), (780, 420)])
    s.arrow([(580, 318), (580, 420)], "via gateway de APIs", (586, 408), anchor="start")
    s.arrow([(310, 380), (310, 420)], "OTLP", (316, 404), anchor="start")
    s.arrow([(40, 119), (10, 119), (10, 445), (40, 445)], "token do cliente", (6, 285), dashed=True, rotate=-90)
    s.save("diagrama-2.svg")


def componentes():
    s = Svg(300)
    s.bound(10, 8, 880, 285, "② Agente (ADK no Agent Runtime)")
    legenda(s, 560, 23, [("llm", "usa LLM"), ("new", "código determinístico")])
    s.box(30, 36, 840, 30, ["Plugins do runner: Model Armor · observabilidade (OpenTelemetry) · emissor de auditoria"])
    s.box(30, 90, 190, 55, ["A. Classificador", "saída estruturada, calibrada"], "llm")
    s.box(260, 90, 300, 55, ["B. Orquestrador (grafo)", "esclarecer · autenticar · confirmar", "executar · responder · escalar"])
    s.box(600, 90, 270, 55, ["H. Configuração versionada", "instruções, persona, textos, critérios"])
    s.box(30, 175, 250, 60, ["C. Agente de conhecimento", "cita fonte · recusa sem fonte", "F. roteador Flash → Pro"], "llm")
    s.box(310, 175, 270, 60, ["D. Subfluxo transacional", "slots → política → confirmação", "→ execução · textos fixos"])
    s.box(610, 175, 260, 60, ["E. Gestor de escalonamento", "gatilhos + resumo para o atendente"], "llm")
    s.box(30, 252, 840, 32, ["G. Registro de ferramentas — leitura: C, D, E · escrita: somente D → RAG Engine, Política, Servidores MCP"])
    s.arrow([(220, 117), (260, 117)])
    s.arrow([(330, 145), (330, 160), (155, 160), (155, 175)])
    s.arrow([(445, 145), (445, 175)])
    s.arrow([(520, 145), (520, 160), (740, 160), (740, 175)])
    for x in (155, 445, 740):
        s.arrow([(x, 235), (x, 252)])
    s.save("diagrama-3.svg")


def sequencia():
    parts = [("Cliente", 60), ("Gateway", 190), ("Agente", 330), ("Política", 470),
             ("Servidor MCP", 600), ("Cartões", 730), ("Barramento", 845)]
    x = dict(parts)
    msgs = [
        ("Cliente", "Gateway", "1 perdi a carteira, bloqueia", False),
        ("Gateway", "Agente", "2 mensagem mascarada", False),
        ("Agente", "Agente", "3 classifica: bloqueio (única chamada ao LLM)", False),
        ("Agente", "Servidor MCP", "4 listar_cartoes", False),
        ("Servidor MCP", "Cartões", "5 consulta", False),
        ("Agente", "Cliente", "6 qual cartão? [botões]", False),
        ("Cliente", "Agente", "7 final 1234", False),
        ("Agente", "Política", "8 pré-check", False),
        ("Política", "Agente", "9 confirmação C, texto fixo", True),
        ("Agente", "Cliente", "10 Bloquear o final 1234? [Sim]", False),
        ("Cliente", "Agente", "11 Sim (botão)", False),
        ("Agente", "Servidor MCP", "12 bloquear(C, idempotência)", False),
        ("Servidor MCP", "Política", "13 aplica a política", False),
        ("Servidor MCP", "Cartões", "14 bloqueio", False),
        ("Servidor MCP", "Barramento", "15 cartao_bloqueado", False),
        ("Agente", "Cliente", "16 bloqueado; desbloqueio só no app", False),
    ]
    step, y0 = 20, 62
    h = y0 + step * len(msgs) + 10
    s = Svg(h)
    for name, cx in parts:
        w = 104
        s.raw(f'<line x1="{cx}" y1="36" x2="{cx}" y2="{h - 4}" class="life"/>')
        kind = "person" if name == "Cliente" else ("ext" if name in ("Cartões", "Barramento") else "new")
        s.box(cx - w / 2, 6, w, 30, [name], kind, rx=18 if kind == "person" else 6)
    for i, (a, b, label, ret) in enumerate(msgs):
        y = y0 + i * step
        if a == b:
            s.raw(f'<rect x="{x[a] + 4}" y="{y - 12}" width="290" height="16" rx="3" class="llm"/>')
            s.arrow([(x[a], y - 6), (x[a] + 22, y - 6), (x[a] + 22, y + 2), (x[a] + 2, y + 2)])
            s.text(x[a] + 28, y, label, "s")
            continue
        x1, x2 = x[a], x[b]
        s.arrow([(x1, y), (x2, y)], label, ((x1 + x2) / 2, y - 4), dashed=ret)
    s.save("diagrama-4.svg")


if __name__ == "__main__":
    contexto()
    containers()
    componentes()
    sequencia()
    print("diagramas gerados:", ", ".join(sorted(p.name for p in OUT.glob("diagrama-*.svg"))))
