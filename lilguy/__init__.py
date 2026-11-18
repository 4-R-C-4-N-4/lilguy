"""lilguy: a scaffold that lets a very small model drive a shell.

The model only maps (goal, state, observation) -> next action. Knowledge lives in
retrieval, syntax in a grammar, safety in a policy layer, and output parsing in a
deterministic digester.
"""
__version__ = "0.1.0"
