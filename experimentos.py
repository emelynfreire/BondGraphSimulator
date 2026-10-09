"""Experimentos de validacao do simulador (resultados para o artigo).

  E1  Precisao: simulacao x solucao analitica em quatro sistemas lineares.
  E2  Convergencia: erro de Euler e RK4 em funcao do passo e ordem observada
      (esperado: ordem 1 para Euler, ordem 4 para RK4).
  E3  Metodos adaptativos: erro, numero de avaliacoes e tempo de cada metodo.

Parametros em experimentos/config.json. Saidas em resultados/:
  exp1_precisao.csv, exp2_convergencia.csv, exp2_ordens.csv, exp3_metodos.csv,
  fig_convergencia.png, resumo.txt e ambiente.json (versoes, configuracao e
  assinatura dos resultados numericos, para conferir a reprodutibilidade).

Uso:   python experimentos.py            ou   docker compose run --rm experimentos
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

import numpy as np

from bondgraph import balanco_energia, carregar, montar, simular

RAIZ = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(RAIZ, "resultados")


# ------------------------------------------------------- solucoes analiticas
# Escritas a partir dos parametros fisicos, sem usar as equacoes geradas pelo
# simulador: sao a referencia independente.
def _segunda_ordem(t, ganho, alfa, w0):
    wd = np.sqrt(w0 ** 2 - alfa ** 2)
    return ganho * (1 - np.exp(-alfa * t) * (np.cos(wd * t) + alfa / wd * np.sin(wd * t)))


def _motor(t, V=12.0, R=1.0, L=0.005, K=0.05, J=2e-4, b=1e-4):
    """Velocidade angular do motor CC: L di/dt = V - R i - K w ; J dw/dt = K i - b w."""
    A = np.array([[-R / L, -K / L], [K / J, -b / J]])        # estados: i, w
    regime = -np.linalg.solve(A, [V / L, 0.0])
    lam, vec = np.linalg.eig(A)
    coef = np.linalg.solve(vec, -regime)
    return (regime[:, None] + (vec * coef) @ np.exp(np.outer(lam, t)))[1].real


CASOS = {
    "rc_serie": {
        "rotulo": "RC série", "sinal": "C1.e", "grandeza": "tensão no capacitor (V)",
        "analitica": lambda t: 10 * (1 - np.exp(-t / (100 * 1e-6)))},
    "rlc_serie": {
        "rotulo": "RLC série", "sinal": "C1.e", "grandeza": "tensão no capacitor (V)",
        "analitica": lambda t: _segunda_ordem(t, 5.0, 10 / (2 * 0.01), 1 / np.sqrt(0.01 * 1e-4))},
    "massa_mola_amortecedor": {
        "rotulo": "Massa-mola-amortecedor", "sinal": "q_K1", "grandeza": "deslocamento (m)",
        "analitica": lambda t: _segunda_ordem(t, 10 / 50, 3 / (2 * 2), np.sqrt(50 / 2))},
    "motor_cc": {
        "rotulo": "Motor CC", "sinal": "J.f", "grandeza": "velocidade angular (rad/s)",
        "analitica": _motor},
}


# ------------------------------------------------------------------ medidas
def _sistema(nome):
    bg, _, _ = carregar(os.path.join(RAIZ, "exemplos", nome + ".json"))
    return montar(bg)


def _erros(res, caso):
    ana = caso["analitica"](res.t)
    dif = res.sinal(caso["sinal"]) - ana
    if not np.all(np.isfinite(dif)):
        return float("inf"), float("inf")
    erro_max = float(np.max(np.abs(dif)) / np.max(np.abs(ana)))
    nrmse = float(np.sqrt(np.mean(dif ** 2)) / (ana.max() - ana.min()))
    return erro_max, nrmse


def _cronometrar(funcao, repeticoes):
    """Executa `funcao` varias vezes; devolve o ultimo resultado e a mediana do tempo."""
    tempos = []
    for _ in range(repeticoes):
        inicio = time.perf_counter()
        resultado = funcao()
        tempos.append(time.perf_counter() - inicio)
    return resultado, float(np.median(tempos))


def _contar_avaliacoes(sistema):
    """Conta as chamadas a f(t, x) feitas pelo integrador."""
    original, contador = sistema.f_estado, {"n": 0}

    def contada(t, x):
        contador["n"] += 1
        return original(t, x)

    sistema.f_estado = contada
    return contador, original


# -------------------------------------------------------------- experimentos
def exp1_precisao(cfg):
    linhas = []
    for nome, par in cfg["casos"].items():
        caso = CASOS[nome]
        res = simular(_sistema(nome), t_final=par["t_final"], metodo="RK45",
                      n_pontos=cfg["n_pontos"])
        erro_max, nrmse = _erros(res, caso)
        linhas.append({"caso": nome, "grandeza": caso["grandeza"], "metodo": res.metodo,
                       "t_final_s": par["t_final"], "erro_max_relativo": erro_max,
                       "nrmse": nrmse,
                       "erro_balanco_energia": balanco_energia(res)["erro_relativo"]})
    return linhas


def exp2_convergencia(cfg):
    conv = cfg["convergencia"]
    linhas, ordens = [], []
    for nome, par in cfg["casos"].items():
        caso, sistema = CASOS[nome], _sistema(nome)
        for metodo in conv["metodos"]:
            passos, erros = [], []
            for n in conv["n_passos"]:
                h = par["t_final"] / n
                res, tempo = _cronometrar(
                    lambda: simular(sistema, t_final=par["t_final"], metodo=metodo, passo=h),
                    cfg["repeticoes_tempo"])
                erro_max, _ = _erros(res, caso)
                linhas.append({"caso": nome, "metodo": metodo, "n_passos": n, "passo_s": h,
                               "erro_max_relativo": erro_max, "tempo_mediano_s": tempo})
                passos.append(h)
                erros.append(erro_max)
            # ordem observada: inclinacao de log(erro) x log(passo) nos passos mais finos
            # que ainda estao acima do piso de arredondamento
            validos = [(h, e) for h, e in zip(passos, erros)
                       if np.isfinite(e) and conv["erro_minimo_no_ajuste"] < e < 1.0]
            validos = validos[-conv["pontos_no_ajuste"]:]
            ordem = float("nan")
            if len(validos) >= 2:
                hs, es = np.log([v[0] for v in validos]), np.log([v[1] for v in validos])
                ordem = float(np.polyfit(hs, es, 1)[0])
            ordens.append({"caso": nome, "metodo": metodo, "ordem_observada": ordem,
                           "ordem_teorica": 1 if metodo == "Euler" else 4,
                           "pontos_usados": len(validos)})
    return linhas, ordens


def exp3_metodos(cfg):
    linhas = []
    for nome, par in cfg["casos"].items():
        caso = CASOS[nome]
        for metodo in cfg["metodos_adaptativos"]:
            sistema = _sistema(nome)
            contador, original = _contar_avaliacoes(sistema)
            res = simular(sistema, t_final=par["t_final"], metodo=metodo,
                          n_pontos=cfg["n_pontos"])
            avaliacoes = contador["n"]
            sistema.f_estado = original
            _, tempo = _cronometrar(
                lambda: simular(sistema, t_final=par["t_final"], metodo=metodo,
                                n_pontos=cfg["n_pontos"]), cfg["repeticoes_tempo"])
            erro_max, nrmse = _erros(res, caso)
            linhas.append({"caso": nome, "metodo": metodo, "erro_max_relativo": erro_max,
                           "nrmse": nrmse, "avaliacoes_f": avaliacoes,
                           "tempo_mediano_s": tempo})
    return linhas


# -------------------------------------------------------------------- saidas
def _fmt(v):
    return f"{v:.6e}" if isinstance(v, float) else str(v)


def _salvar_csv(nome, linhas):
    with open(os.path.join(SAIDA, nome), "w", newline="", encoding="utf-8") as arq:
        escritor = csv.DictWriter(arq, fieldnames=list(linhas[0]))
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({k: _fmt(v) for k, v in linha.items()})


def _assinatura(*tabelas):
    """SHA-256 dos resultados numericos (sem os tempos, que variam entre execucoes)."""
    h = hashlib.sha256()
    for tabela in tabelas:
        for linha in tabela:
            for chave, valor in linha.items():
                if not chave.startswith("tempo"):
                    h.update(f"{chave}={_fmt(valor)};".encode())
    return h.hexdigest()


def _tabela(linhas, colunas):
    larguras = [max(len(c), *(len(_fmt_curto(l[c])) for l in linhas)) for c in colunas]
    texto = ["  ".join(c.ljust(w) for c, w in zip(colunas, larguras))]
    for l in linhas:
        texto.append("  ".join(_fmt_curto(l[c]).ljust(w) for c, w in zip(colunas, larguras)))
    return "\n".join(texto)


def _fmt_curto(v):
    if isinstance(v, float):
        return f"{v:.3g}" if (v == 0 or 1e-3 <= abs(v) < 1e4) else f"{v:.2e}"
    return str(v)


def _figura_convergencia(cfg, linhas, ordens):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker

    estilo = {"Euler": ("#2a78d6", "o"), "RK4": ("#eb6834", "s")}
    tinta, suave, grade = "#0b0b0b", "#898781", "#e1e0d9"
    nomes = list(cfg["casos"])
    fig, eixos = plt.subplots(1, len(nomes), figsize=(3.1 * len(nomes), 3.4), sharey=True)
    fig.patch.set_facecolor("#fcfcfb")
    for ax, nome in zip(np.atleast_1d(eixos), nomes):
        ax.set_facecolor("#fcfcfb")
        for metodo, (cor, marca) in estilo.items():
            pts = [(l["passo_s"], l["erro_max_relativo"]) for l in linhas
                   if l["caso"] == nome and l["metodo"] == metodo
                   and np.isfinite(l["erro_max_relativo"])]
            if not pts:
                continue
            hs, es = np.array(pts).T
            ordem = next(o["ordem_observada"] for o in ordens
                         if o["caso"] == nome and o["metodo"] == metodo)
            ax.loglog(hs, es, color=cor, marker=marca, ms=5, lw=2,
                      label=f"{metodo} (ordem {ordem:.2f})")
        ax.set_title(CASOS[nome]["rotulo"], fontsize=10, color=tinta)
        ax.set_xlabel("passo de integração (s)", fontsize=9, color=tinta)
        ax.grid(True, which="major", color=grade, lw=0.8)
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.tick_params(colors=suave, labelsize=8)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            ax.spines[lado].set_color("#c3c2b7")
        ax.legend(fontsize=8, frameon=False, loc="lower right", labelcolor=tinta)
    np.atleast_1d(eixos)[0].set_ylabel("erro máximo relativo", fontsize=9, color=tinta)
    fig.tight_layout()
    fig.savefig(os.path.join(SAIDA, "fig_convergencia.png"), dpi=200)


def _commit_git():
    try:
        with open(os.path.join(RAIZ, ".git", "HEAD"), encoding="utf-8") as arq:
            cabeca = arq.read().strip()
        if cabeca.startswith("ref: "):
            with open(os.path.join(RAIZ, ".git", *cabeca[5:].split("/")), encoding="utf-8") as arq:
                return arq.read().strip()
        return cabeca
    except OSError:
        return None


def _versoes():
    from importlib.metadata import PackageNotFoundError, version
    saida = {}
    for pacote in ("numpy", "scipy", "sympy", "networkx", "matplotlib"):
        try:
            saida[pacote] = version(pacote)
        except PackageNotFoundError:
            saida[pacote] = None
    return saida


def main():
    with open(os.path.join(RAIZ, "experimentos", "config.json"), encoding="utf-8") as arq:
        cfg = json.load(arq)
    np.random.seed(cfg["semente"])
    os.makedirs(SAIDA, exist_ok=True)
    inicio = time.perf_counter()

    print("E1: precisao...", flush=True)
    e1 = exp1_precisao(cfg)
    print("E2: convergencia...", flush=True)
    e2, ordens = exp2_convergencia(cfg)
    print("E3: metodos adaptativos...", flush=True)
    e3 = exp3_metodos(cfg)

    _salvar_csv("exp1_precisao.csv", e1)
    _salvar_csv("exp2_convergencia.csv", e2)
    _salvar_csv("exp2_ordens.csv", ordens)
    _salvar_csv("exp3_metodos.csv", e3)
    _figura_convergencia(cfg, e2, ordens)

    assinatura = _assinatura(e1, e2, ordens, e3)
    resumo = "\n\n".join([
        "E1  PRECISAO (simulacao x solucao analitica, metodo RK45)\n" + _tabela(
            e1, ["caso", "erro_max_relativo", "nrmse", "erro_balanco_energia"]),
        "E2  ORDEM DE CONVERGENCIA OBSERVADA\n" + _tabela(
            ordens, ["caso", "metodo", "ordem_observada", "ordem_teorica", "pontos_usados"]),
        "E3  METODOS ADAPTATIVOS\n" + _tabela(
            e3, ["caso", "metodo", "erro_max_relativo", "avaliacoes_f", "tempo_mediano_s"]),
        f"Assinatura dos resultados numericos (SHA-256): {assinatura}",
    ])
    with open(os.path.join(SAIDA, "resumo.txt"), "w", encoding="utf-8") as arq:
        arq.write(resumo + "\n")
    with open(os.path.join(SAIDA, "ambiente.json"), "w", encoding="utf-8") as arq:
        json.dump({
            "executado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duracao_s": round(time.perf_counter() - inicio, 2),
            "python": sys.version.split()[0],
            "plataforma": platform.platform(),
            "processador": platform.machine(),
            "em_docker": os.path.exists("/.dockerenv"),
            "pacotes": _versoes(),
            "commit_git": _commit_git(),
            "assinatura_resultados_sha256": assinatura,
            "configuracao": cfg,
        }, arq, indent=2, ensure_ascii=False)
    print("\n" + resumo)
    print(f"\nArquivos gravados em {SAIDA}")


if __name__ == "__main__":
    main()
