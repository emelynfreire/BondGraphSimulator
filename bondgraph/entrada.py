"""Modulo de entrada: JSON ou texto em portugues -> Bond Graph.

Tres formas de descrever o sistema:

1. Texto livre simples, por exemplo
   "Um resistor de 100 Ohms em serie com um capacitor de 1 uF conectado a uma
    fonte de tensao de 10V"
   (interpretado por regras: palavras-chave, valores com unidade, serie/paralelo).

2. JSON no formato "circuito" (arvore serie/paralelo):
   {"formato": "circuito", "fonte": {"tipo": "tensao", "valor": 10},
    "circuito": {"serie": [{"R": 100}, {"C": 1e-6}]}}

3. JSON no formato "bondgraph" (elementos e bonds explicitos), para qualquer
   topologia, inclusive multidominio com TF e GY.

Regra de conversao circuito -> Bond Graph:
   serie    -> juncao 1 (fluxo comum);   paralelo -> juncao 0 (esforco comum).
"""
from __future__ import annotations

import json
import re
import unicodedata

from .modelo import BondGraph, ErroBondGraph

# componente -> (tipo no Bond Graph, prefixo do nome, dominio, descricao, unidade esperada)
COMPONENTES = {
    "R": ("R", "R", "eletrico", "resistor", "ohm"),
    "C": ("C", "C", "eletrico", "capacitor", "F"),
    "L": ("I", "L", "eletrico", "indutor", "H"),
    "diodo": ("R", "D", "eletrico", "diodo", None),
    "massa": ("I", "M", "mecanico", "massa", "kg"),
    "mola": ("C", "K", "mecanico", "mola", "N/m"),
    "amortecedor": ("R", "B", "mecanico", "amortecedor", "N.s/m"),
}
FONTES = {  # tipo de fonte -> (tipo BG, nome, dominio)
    "tensao": ("Se", "V", "eletrico"), "corrente": ("Sf", "If", "eletrico"),
    "forca": ("Se", "F", "mecanico"), "velocidade": ("Sf", "Vel", "mecanico"),
}
PREFIXOS = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3,
            "k": 1e3, "M": 1e6, "G": 1e9, None: 1.0, "": 1.0}


# ====================================================================== API
def carregar(entrada) -> tuple[BondGraph, dict, list[str]]:
    """Aceita dict, texto JSON, caminho de arquivo .json ou texto livre.

    Retorna (bond_graph, opcoes_de_simulacao, notas_de_interpretacao).
    """
    notas: list[str] = []
    if isinstance(entrada, dict):
        desc = entrada
    else:
        txt = str(entrada).strip()
        if txt.lower().endswith(".json"):
            with open(txt, encoding="utf-8") as arq:
                desc = json.load(arq)
        elif txt.startswith("{"):
            desc = json.loads(txt)
        else:
            desc, notas = interpretar_texto(txt)
    formato = desc.get("formato", "bondgraph" if "bonds" in desc else "circuito")
    bg = _de_bondgraph(desc) if formato == "bondgraph" else _de_circuito(desc)
    return bg, dict(desc.get("simulacao", {})), notas


# ============================================================ JSON bondgraph
def _de_bondgraph(desc: dict) -> BondGraph:
    bg = BondGraph(desc.get("nome", "sistema"), desc.get("dominio", "generico"))
    for el in desc["elementos"]:
        el = dict(el)
        tipo, nome = el.pop("tipo"), el.pop("nome", None)
        valor = el.pop("valor", None)
        if tipo in ("Se", "Sf"):
            el["fonte"] = _sinal(el.pop("fonte", valor if valor is not None else 0.0))
            valor = None
        bg.adicionar(tipo, nome, valor, **el)
    for origem, destino in desc["bonds"]:
        bg.ligar(origem, destino)
    return bg


def _sinal(v) -> dict:
    """Normaliza a descricao do sinal de uma fonte."""
    if isinstance(v, dict):
        return v if "tipo" in v else {"tipo": "constante", **v}
    return {"tipo": "constante", "valor": float(v)}


# ============================================================= JSON circuito
def _de_circuito(desc: dict) -> BondGraph:
    fonte = desc.get("fonte")
    if not fonte:
        raise ErroBondGraph("A descricao nao tem fonte (tensao, corrente, forca ou velocidade).")
    tipo_f = fonte.get("tipo", "tensao")
    if tipo_f not in FONTES:
        raise ErroBondGraph(f"Tipo de fonte desconhecido: {tipo_f!r}. Use um de {list(FONTES)}.")
    tipo_bg, nome_f, dominio = FONTES[tipo_f]
    bg = BondGraph(desc.get("nome", "sistema"), desc.get("dominio", dominio))

    arvore = desc.get("circuito")
    if not arvore:
        raise ErroBondGraph("A descricao nao tem componentes.")
    if "serie" not in arvore and "paralelo" not in arvore:
        arvore = {"serie": [arvore]}

    sinal = _sinal(fonte.get("sinal", fonte.get("valor", 0.0)))
    f = bg.adicionar(tipo_bg, f"{nome_f}1", fonte=sinal, rotulo=f"fonte de {tipo_f}")
    topo = _construir(bg, arvore, None)
    bg.ligar(f, topo)
    return bg


def _construir(bg: BondGraph, item: dict, pai: str | None) -> str:
    """Cria recursivamente juncoes e elementos; retorna o nome do no criado."""
    chave = next((k for k in ("serie", "paralelo") if k in item), None)
    if chave:
        tipo_j = "1" if chave == "serie" else "0"
        filhos = []
        for filho in item[chave]:          # achata serie-dentro-de-serie etc.
            filhos += filho[chave] if chave in filho else [filho]
        if len(filhos) == 1 and pai is not None:
            return _construir(bg, filhos[0], pai)
        j = bg.adicionar(tipo_j)
        if pai is not None:
            bg.ligar(pai, j)
        for filho in filhos:
            _construir(bg, filho, j)
        return j

    comp = next((k for k in COMPONENTES if k in item), None)
    if comp is None:
        raise ErroBondGraph(f"Componente nao reconhecido: {item}. Use um de {list(COMPONENTES)}.")
    tipo_bg, prefixo, _, descricao, _ = COMPONENTES[comp]
    nome = item.get("nome") or bg._novo_nome(prefixo)
    valor = item[comp]
    if comp == "diodo":
        params = valor if isinstance(valor, dict) else {}
        bg.adicionar("R", nome, lei="diodo", params=params, rotulo=descricao)
    else:
        valor = float(valor)
        if comp == "mola":                  # rigidez k -> complacencia C = 1/k
            valor = 1.0 / valor
        bg.adicionar(tipo_bg, nome, valor, rotulo=f"{descricao} {item[comp]:g}")
    if pai is not None:
        bg.ligar(pai, nome)
    return nome


# ============================================================== texto livre
_PALAVRAS = [
    (r"fonte\s+de\s+tensao|bateria|fonte\s+de\s+alimentacao", ("fonte", "tensao")),
    (r"fonte\s+de\s+corrente", ("fonte", "corrente")),
    (r"forca", ("fonte", "forca")),
    (r"resistor(?:es)?|resistencia", ("comp", "R")),
    (r"capacitor(?:es)?|capacitancia", ("comp", "C")),
    (r"indutor(?:es)?|bobina|indutancia", ("comp", "L")),
    (r"diodo", ("comp", "diodo")),
    (r"massa", ("comp", "massa")),
    (r"mola", ("comp", "mola")),
    (r"amortecedor", ("comp", "amortecedor")),
]
_NUM = r"(?P<num>\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)"
_VALOR = re.compile(
    _NUM + r"\s*(?:(?P<kg>kg)|(?P<pref>[pnuµμmkMG])?\s?"
    r"(?P<un>[Oo]hms?|Ω|Ω|Hz|F|H|V|A|N\.?s/m|N/m|N|farads?|henrys?|volts?|amperes?))(?![A-Za-z])")
_TEMPO = re.compile(r"(?:simul\w*|durante|por)\s+(?:por\s+|durante\s+)?" + _NUM
                    + r"\s*(?P<un>ms|us|µs|μs|s|segundos?)\b")


def _sem_acento(txt: str) -> str:
    """Remove acentos e passa a minusculas, preservando o comprimento do texto."""
    saida = []
    for ch in txt:
        base = unicodedata.normalize("NFD", ch)[0]
        saida.append(base.lower() if len(base) == 1 else ch)
    return "".join(saida)


def _valores(trecho: str) -> list[tuple[float, str]]:
    achados = []
    for m in _VALOR.finditer(trecho):
        num = float(m.group("num").replace(",", "."))
        if m.group("kg"):
            achados.append((num, "kg"))
            continue
        un = m.group("un")
        un = {"ohms": "ohm", "Ohm": "ohm", "Ohms": "ohm", "Ω": "ohm", "Ω": "ohm"}.get(un, un)
        un = {"farad": "F", "farads": "F", "henry": "H", "henrys": "H", "volt": "V",
              "volts": "V", "ampere": "A", "amperes": "A", "Ns/m": "N.s/m"}.get(un, un)
        achados.append((num * PREFIXOS[m.group("pref")], un))
    return achados


def interpretar_texto(texto: str) -> tuple[dict, list[str]]:
    """Converte uma descricao em portugues no formato JSON 'circuito'."""
    limpo = _sem_acento(texto)
    achados = []
    for padrao, info in _PALAVRAS:
        for m in re.finditer(r"\b(?:" + padrao + r")\b", limpo):
            achados.append((m.start(), m.end(), info))
    achados.sort()
    if not achados:
        raise ErroBondGraph("Nao reconheci nenhum componente na descricao.")

    notas, fonte, comps, posicoes = [], None, [], []
    for k, (ini, fim, (classe, tipo)) in enumerate(achados):
        prox = achados[k + 1][0] if k + 1 < len(achados) else len(texto)
        trecho_orig, trecho = texto[fim:prox], limpo[fim:prox]
        vals = _valores(trecho_orig)
        if classe == "fonte":
            if fonte is not None:
                notas.append("Aviso: mais de uma fonte no texto; usei apenas a primeira.")
                continue
            amp = next((v for v, u in vals if u in ("V", "A", "N")), None)
            freq = next((v for v, u in vals if u == "Hz"), None)
            if amp is None:
                raise ErroBondGraph(f"Nao encontrei o valor da fonte de {tipo}.")
            if freq is not None or re.search(r"senoidal|alternada", trecho):
                freq = freq if freq is not None else 60.0
                fonte = {"tipo": tipo, "sinal": {"tipo": "seno", "amplitude": amp, "frequencia": freq}}
                notas.append(f"Fonte de {tipo} senoidal: amplitude {amp:g}, {freq:g} Hz")
            else:
                fonte = {"tipo": tipo, "valor": amp}
                notas.append(f"Fonte de {tipo} constante: {amp:g}")
        else:
            un_esperada = COMPONENTES[tipo][4]
            if tipo == "diodo":
                comps.append({"diodo": {}})
                notas.append("Diodo (modelo de Shockley, parametros padrao)")
            else:
                if not vals:                # numero sem unidade: assume a unidade padrao
                    m = re.search(_NUM, trecho_orig)
                    if not m:
                        raise ErroBondGraph(
                            f"Nao encontrei o valor do componente '{COMPONENTES[tipo][3]}'.")
                    vals = [(float(m.group("num").replace(",", ".")), un_esperada)]
                valor, un = vals[0]
                if un != un_esperada:
                    notas.append(f"Aviso: {COMPONENTES[tipo][3]} com unidade '{un}' "
                                 f"(esperado '{un_esperada}'); usei o valor {valor:g}.")
                comps.append({tipo: valor})
                notas.append(f"{COMPONENTES[tipo][3].capitalize()}: {valor:g} {un_esperada} "
                             f"-> elemento {COMPONENTES[tipo][0]}")
            posicoes.append((ini, fim))

    if fonte is None:
        raise ErroBondGraph("Nao encontrei a fonte (de tensao, de corrente ou forca) na descricao.")
    if not comps:
        raise ErroBondGraph("Nao encontrei componentes alem da fonte.")

    mecanico = FONTES[fonte["tipo"]][2] == "mecanico"
    if mecanico:
        arvore = {"serie": comps}
        notas.append("Sistema mecanico: componentes presos ao mesmo corpo (mesma velocidade) "
                     "-> juncao 1.")
    else:
        # ligacao entre componentes consecutivos: "serie" ou "paralelo"
        ligs = []
        for k in range(len(comps) - 1):
            entre = limpo[posicoes[k][1]:posicoes[k + 1][0]]
            ligs.append("paralelo" if "paralel" in entre else "serie" if "serie" in entre else None)
        fim_txt = limpo[posicoes[-1][1]:]
        ultimo = "paralelo" if "paralel" in fim_txt else "serie" if "serie" in fim_txt else None
        for k in range(len(ligs) - 1, -1, -1):          # herda a proxima ligacao explicita
            ultimo = ligs[k] = ligs[k] or ultimo
        # sem ligacao explicita entre os componentes: vale a unica citada no texto
        geral = "paralelo" if ("paralel" in limpo and "serie" not in limpo) else "serie"
        ligs = [lg or next((x for x in ligs if x), geral) for lg in ligs]
        # paralelo tem precedencia sobre serie
        grupos, atual = [], [comps[0]]
        for comp, lg in zip(comps[1:], ligs):
            if lg == "paralelo":
                atual.append(comp)
            else:
                grupos.append(atual)
                atual = [comp]
        grupos.append(atual)
        itens = [g[0] if len(g) == 1 else {"paralelo": g} for g in grupos]
        arvore = itens[0] if len(itens) == 1 and "paralelo" in itens[0] else {"serie": itens}
        notas.append("Topologia: " + _descrever(arvore))

    desc = {"formato": "circuito", "nome": "sistema descrito em texto", "fonte": fonte,
            "circuito": arvore}
    m = _TEMPO.search(texto)
    if m:
        fator = {"ms": 1e-3, "us": 1e-6, "µs": 1e-6, "μs": 1e-6}.get(m.group("un"), 1.0)
        desc["simulacao"] = {"t_final": float(m.group("num").replace(",", ".")) * fator}
        notas.append(f"Tempo de simulacao: {desc['simulacao']['t_final']:g} s")
    return desc, notas


def _descrever(item: dict) -> str:
    for chave in ("serie", "paralelo"):
        if chave in item:
            return chave + "(" + ", ".join(_descrever(x) for x in item[chave]) + ")"
    comp = next(k for k in COMPONENTES if k in item)
    return comp if comp == "diodo" else f"{comp}={item[comp]:g}"
