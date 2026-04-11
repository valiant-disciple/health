"""
DSPy Module definitions.

Each Module wraps one or more Predict/ChainOfThought calls and can be
compiled by MIPROv2 — the optimiser replaces the instruction text and
injects few-shot demonstrations to improve output quality.
"""
from __future__ import annotations
import dspy
from dspy_programs.signatures import LabInterpretSignature, ChatContextSignature


class LabInterpretProgram(dspy.Module):
    """
    Interprets a patient's lab results in the context of their full health profile.
    Compiled output is saved to dspy_compiled/interpret.json.
    """

    def __init__(self):
        self.interpret = dspy.Predict(LabInterpretSignature)

    def forward(self, patient_context: str, lab_results: str) -> dspy.Prediction:
        return self.interpret(
            patient_context=patient_context,
            lab_results=lab_results,
        )


class ChatContextProgram(dspy.Module):
    """
    Distills patient memories into a focused context snippet for the chat agent.
    Uses ChainOfThought to reason about which memories are most relevant.
    Compiled output is saved to dspy_compiled/chat_context.json.
    """

    def __init__(self):
        self.refine = dspy.ChainOfThought(ChatContextSignature)

    def forward(self, memories: str, question: str) -> dspy.Prediction:
        return self.refine(memories=memories, question=question)
