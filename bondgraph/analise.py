"""Analise automatica do modelo e do resultado da simulacao.

Verificacoes baseadas em regras (nao usam aprendizado de maquina):
  - estabilidade, constantes de tempo, amortecimento e rigidez (autovalores);
  - adequacao do tempo final e do passo de integracao;
  - balanco de energia: energia fornecida = armazenada + dissipada;
  - valores nao finitos e sobressinal.
Cada item devolve (nivel, mensagem), com nivel em {"ok", "info", "aviso", "erro"}.
"""
from __future__ import annotations

import numpy as np

from .simulacao import Resultado


def balanco_energia(res: Resultado) -> dict:
    """Energia fornecida pelas fontes, dissipada nos R e armazenada em C e I."""
    sis, bg = res.sistema, res.sistema.bg
    trapezio = getattr(np, "trapezoid", None) or np.trapz    # NumPy 2.x ou 1.x
    integ = lambda y: float(trapezio(y, res.t))
    fornecida = dissipada = 0.0
    for no in bg.nos:
        if no.tipo in ("Se", "Sf", "R"):
            (_, s), = bg.bonds_do_no(no.nome)          # s = +1: bond entra no elemento
            energia = s * integ(res.sinais[f"{no.nome}.P"])
            if no.tipo == "R":
                dissipada += energia
            else:
                fornecida -= energia
    def armazenada(k):
        total = 0.0
        for nome_el, x in zip(sis.elementos_estado, res.x[:, k]):
            total += x ** 2 / (2 * sis.valor(nome_el))  # q^2/2C ou p^2/2I
        return total
    delta = armazenada(-1) - armazenada(0)
    escala = max(abs(fornecida), abs(dissipada), abs(delta), 1e-300)
    return {"fornecida": fornecida, "dissipada": dissipada, "armazenada": delta,
            "erro_relativo": abs(fornecida - dissipada - delta) / escala}


def diagnosticar(res: Resultado) -> list[tuple[str, str]]:
    sis = res.sistema
    itens: list[tuple[str, str]] = [("info", a) for a in res.avisos]

    # ---- valores nao finitos
    if not np.all(np.isfinite(res.x)):
        itens.append(("erro", "A simulacao divergiu (valores infinitos ou NaN). Com metodos de "
                              "passo fixo, reduza o passo; ou use o metodo 'auto'/'Radau'."))
        return itens

    # ---- autovalores (no estado final, o que tambem cobre sistemas nao lineares)
    lam = np.linalg.eigvals(sis.jacobiana(res.t[-1], res.x[:, -1]))
    escala = max(1.0, float(np.max(np.abs(lam), initial=0.0)))
    if np.any(lam.real > 1e-8 * escala):
        itens.append(("erro", f"Modelo instavel: autovalor com parte real positiva "
                              f"({lam[np.argmax(lam.real)]:.4g}). Verifique sinais dos bonds e "
                              f"parametros negativos."))
    amort = np.abs(lam.real)[np.abs(lam.real) > 1e-9 * escala]
    if amort.size:
        tau_lento, tau_rapido = 1 / amort.min(), 1 / amort.max()
        itens.append(("info", f"Constantes de tempo: de {tau_rapido:.3g} s a {tau_lento:.3g} s."))
        if res.t_final < 3 * tau_lento:
            itens.append(("aviso", f"O tempo final ({res.t_final:.3g} s) e menor que 3 constantes "
                                   f"de tempo do modo mais lento: o transitorio nao terminou. "
                                   f"Sugestao: t_final ~ {5 * tau_lento:.3g} s."))
        elif res.t_final > 100 * tau_lento:
            itens.append(("aviso", f"O tempo final e mais de 100 vezes a maior constante de tempo: "
                                   f"quase toda a simulacao mostra o regime permanente. "
                                   f"Sugestao: t_final ~ {5 * tau_lento:.3g} s."))
    osc = lam[lam.imag > 1e-9 * escala]
    for l in osc:
        wn = abs(l)
        zeta = -l.real / wn
        itens.append(("info", f"Modo oscilatorio: frequencia natural {wn / (2 * np.pi):.4g} Hz, "
                              f"fator de amortecimento {zeta:.3g}."))
        if 0 <= zeta < 0.05:
            itens.append(("aviso", "Sistema muito pouco amortecido: oscilacoes longas. Confira se "
                                   "falta algum elemento dissipativo (R) no modelo."))
    mods = np.abs(lam)[np.abs(lam) > 0]
    if mods.size:
        rigidez = mods.max() / mods.min()
        if rigidez > 1e3:
            itens.append(("aviso", f"Sistema rigido (razao entre dinamicas ~ {rigidez:.2g}). Prefira "
                                   f"metodos implicitos (Radau, BDF). Se a dinamica rapida nao "
                                   f"interessa, o elemento associado pode ser desprezado para "
                                   f"simplificar o modelo."))
        # ---- passo fixo: limite de estabilidade
        if res.passo is not None:
            limite = (2.0 if res.metodo == "Euler" else 2.78) / mods.max()
            if res.passo > limite:
                itens.append(("erro", f"Passo {res.passo:.3g} s acima do limite de estabilidade do "
                                      f"metodo {res.metodo} (~{limite:.3g} s)."))
            elif res.passo > limite / 10:
                itens.append(("aviso", f"Passo {res.passo:.3g} s proximo do limite de estabilidade "
                                       f"(~{limite:.3g} s): a precisao pode ser baixa."))

    # ---- balanco de energia
    be = balanco_energia(res)
    texto = (f"Balanco de energia: fornecida {be['fornecida']:.4g} J = dissipada "
             f"{be['dissipada']:.4g} J + armazenada {be['armazenada']:.4g} J "
             f"(erro {100 * be['erro_relativo']:.2g} %).")
    if be["erro_relativo"] > 0.02:
        itens.append(("aviso", texto + " Erro acima de 2 %: reduza o passo, aumente o numero de "
                                       "pontos ou troque o metodo de integracao."))
    else:
        itens.append(("ok", texto))

    # ---- sobressinal nos estados
    senoidal = any(n.tipo in ("Se", "Sf") and n.fonte.get("tipo") == "seno" for n in sis.bg.nos)
    for nome, x in zip(sis.nomes_estados, res.x):
        final, pico = x[-1], x[np.argmax(np.abs(x))]
        if not senoidal and abs(final) > 0.05 * abs(pico) and pico / final > 1.05:
            itens.append(("info", f"Pico de {nome}: {pico / final:.3g} vezes o valor final."))
    return itens


def texto_diagnostico(itens) -> str:
    marca = {"ok": "[ok]   ", "info": "[info] ", "aviso": "[AVISO]", "erro": "[ERRO] "}
    return "\n".join(f"{marca[n]} {m}" for n, m in itens)
