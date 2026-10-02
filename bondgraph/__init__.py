"""Simulador simples de Bond Graph (prototipo de validacao)."""
from .modelo import BondGraph, ErroBondGraph
from .entrada import carregar, interpretar_texto
from .equacoes import montar
from .simulacao import simular, METODOS
from .analise import diagnosticar, balanco_energia

__all__ = ["BondGraph", "ErroBondGraph", "carregar", "interpretar_texto", "montar",
           "simular", "METODOS", "diagnosticar", "balanco_energia"]
