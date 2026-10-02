"""Estrutura de dados do Bond Graph.

Um Bond Graph e representado como um grafo direcionado (NetworkX):
  - nos  = elementos (Se, Sf, R, C, I, TF, GY) e juncoes (0 e 1);
  - arcos = bonds. O sentido do arco e o sentido positivo da potencia
    (a "meia seta" do diagrama).

Cada bond carrega duas variaveis: esforco (e) e fluxo (f); potencia = e * f.

Convencao de juncoes usada aqui (a padrao da literatura):
  - juncao 1: fluxo comum, soma algebrica dos esforcos = 0 (ligacao em serie);
  - juncao 0: esforco comum, soma algebrica dos fluxos = 0 (ligacao em paralelo).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import networkx as nx

TIPOS_ELEMENTO = ("Se", "Sf", "R", "C", "I", "TF", "GY")
TIPOS_JUNCAO = ("0", "1")
TIPOS = TIPOS_ELEMENTO + TIPOS_JUNCAO


class ErroBondGraph(Exception):
    """Erro de construcao ou de consistencia do Bond Graph."""


@dataclass
class No:
    nome: str
    tipo: str
    valor: Optional[float] = None          # parametro (R, C, I, razao do TF/GY)
    fonte: Optional[dict] = None           # sinal da fonte (Se/Sf)
    lei: Optional[str] = None              # R nao linear: "diodo" ou "funcao"
    params: dict = field(default_factory=dict)
    funcao: Optional[Callable] = None      # R nao linear: f = funcao(e)
    rotulo: str = ""                       # descricao legivel (ex.: "resistor 100 ohm")


class BondGraph:
    """Bond Graph com elementos, juncoes e bonds numerados."""

    def __init__(self, nome: str = "sistema", dominio: str = "eletrico"):
        self.nome = nome
        self.dominio = dominio
        self.g = nx.DiGraph()
        self._n_bonds = 0
        self._contadores: dict[str, int] = {}

    # ------------------------------------------------------------------ nos
    def _novo_nome(self, prefixo: str) -> str:
        self._contadores[prefixo] = self._contadores.get(prefixo, 0) + 1
        return f"{prefixo}{self._contadores[prefixo]}"

    def adicionar(self, tipo: str, nome: str | None = None, valor=None, **kw) -> str:
        if tipo not in TIPOS:
            raise ErroBondGraph(f"Tipo desconhecido: {tipo!r}. Use um de {TIPOS}.")
        if nome is None:
            nome = self._novo_nome("J" if tipo in TIPOS_JUNCAO else tipo)
        if nome in self.g:
            raise ErroBondGraph(f"Ja existe um no chamado {nome!r}.")
        if tipo in ("Se", "Sf") and kw.get("fonte") is None:
            kw["fonte"] = {"tipo": "constante", "valor": float(valor if valor is not None else 0.0)}
        self.g.add_node(nome, no=No(nome=nome, tipo=tipo, valor=valor, **kw))
        return nome

    def no(self, nome: str) -> No:
        return self.g.nodes[nome]["no"]

    @property
    def nos(self) -> list[No]:
        return [self.g.nodes[n]["no"] for n in self.g.nodes]

    # ---------------------------------------------------------------- bonds
    def ligar(self, origem: str, destino: str) -> int:
        """Cria um bond origem -> destino (sentido positivo da potencia)."""
        for n in (origem, destino):
            if n not in self.g:
                raise ErroBondGraph(f"No inexistente: {n!r}.")
        if self.g.has_edge(origem, destino) or self.g.has_edge(destino, origem):
            raise ErroBondGraph(f"Ja existe um bond entre {origem} e {destino}.")
        self._n_bonds += 1
        self.g.add_edge(origem, destino, id=self._n_bonds)
        return self._n_bonds

    @property
    def bonds(self) -> list[tuple[int, str, str]]:
        """Lista (id, origem, destino) ordenada pelo numero do bond."""
        return sorted((d["id"], u, v) for u, v, d in self.g.edges(data=True))

    def bonds_do_no(self, nome: str) -> list[tuple[int, int]]:
        """Bonds ligados ao no: lista (id, sinal); sinal +1 se o bond ENTRA no no."""
        entra = [(d["id"], +1) for _, _, d in self.g.in_edges(nome, data=True)]
        sai = [(d["id"], -1) for _, _, d in self.g.out_edges(nome, data=True)]
        return sorted(entra + sai)

    # ------------------------------------------------------------ validacao
    def validar(self) -> None:
        if self.g.number_of_nodes() == 0:
            raise ErroBondGraph("O Bond Graph esta vazio.")
        if not nx.is_weakly_connected(self.g):
            raise ErroBondGraph("O Bond Graph tem partes desconectadas.")
        for no in self.nos:
            k = len(self.bonds_do_no(no.nome))
            if no.tipo in ("Se", "Sf", "R", "C", "I") and k != 1:
                raise ErroBondGraph(
                    f"O elemento {no.nome} ({no.tipo}) tem {k} bonds; deve ter exatamente 1.")
            if no.tipo in ("TF", "GY"):
                if k != 2 or self.g.in_degree(no.nome) != 1:
                    raise ErroBondGraph(
                        f"{no.nome} ({no.tipo}) precisa de 1 bond entrando e 1 saindo.")
            if no.tipo in TIPOS_JUNCAO and k < 2:
                raise ErroBondGraph(f"A juncao {no.nome} precisa de pelo menos 2 bonds.")
            if no.tipo in ("R", "C", "I", "TF", "GY") and no.lei is None:
                if no.valor is None or float(no.valor) == 0.0:
                    raise ErroBondGraph(f"O elemento {no.nome} precisa de um valor nao nulo.")
        if not any(n.tipo in ("C", "I") for n in self.nos):
            raise ErroBondGraph(
                "O sistema nao tem elementos armazenadores (C ou I): nao ha dinamica a simular.")

    # ------------------------------------------------------------- exibicao
    def resumo(self) -> str:
        linhas = [f"Bond Graph '{self.nome}' (dominio: {self.dominio})", "Nos:"]
        for no in self.nos:
            extra = ""
            if no.tipo in ("Se", "Sf"):
                extra = f"  fonte={no.fonte}"
            elif no.lei:
                extra = f"  lei={no.lei} {no.params or ''}"
            elif no.valor is not None:
                extra = f"  valor={no.valor:g}"
            if no.rotulo:
                extra += f"  [{no.rotulo}]"
            linhas.append(f"  {no.nome:<6} tipo {no.tipo:<3}{extra}")
        linhas.append("Bonds (origem -> destino):")
        for i, u, v in self.bonds:
            linhas.append(f"  bond {i}: {u} -> {v}")
        return "\n".join(linhas)

    def para_dict(self) -> dict:
        elementos = []
        for no in self.nos:
            d = {"nome": no.nome, "tipo": no.tipo}
            if no.tipo in ("Se", "Sf"):
                d["fonte"] = no.fonte
            elif no.lei:
                d["lei"], d["params"] = no.lei, no.params
            elif no.valor is not None:
                d["valor"] = no.valor
            elementos.append(d)
        return {"formato": "bondgraph", "nome": self.nome, "dominio": self.dominio,
                "elementos": elementos, "bonds": [[u, v] for _, u, v in self.bonds]}
