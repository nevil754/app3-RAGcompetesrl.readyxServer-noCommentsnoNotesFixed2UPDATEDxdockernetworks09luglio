from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

@dataclass
class ValidationResult:
    is_valid: bool
    answer: str
    issues: list[str]
    was_modified: bool = False

_FALLBACK_ANSWER = (
    "Mi dispiace, non sono riuscito a generare una risposta appropriata. "
    "Prova a riformulare la domanda."
)

_MIN_LENGTH = 20

_MAX_LENGTH = 8000

_EMPTY_PATTERNS = {
    "n/a", "n.a.", "nessuna risposta", "non lo so",
    "non disponibile", "nessun risultato", "...", "---",
}

def validate_answer(
    answer: str,
    question: str,
    min_length: int = _MIN_LENGTH,
    max_length: int = _MAX_LENGTH,
) -> ValidationResult:
    issues: list[str] = []
    modified = False

    if not answer or not answer.strip():
        logger.warning("Risposta LLM vuota", question=question[:100])
        return ValidationResult(
            is_valid=False,
            answer=_FALLBACK_ANSWER,
            issues=["risposta vuota"],
            was_modified=True,
        )

    answer = answer.strip()

    answer_lower = answer.lower().strip(".,! \n")
    if answer_lower in _EMPTY_PATTERNS or len(answer_lower) < 3:
        logger.warning("Risposta LLM con pattern vuoto", answer=answer[:50])
        return ValidationResult(
            is_valid=False,
            answer=_FALLBACK_ANSWER,
            issues=["pattern risposta vuota"],
            was_modified=True,
        )

    if len(answer) < min_length:
        issues.append(f"risposta troppo corta ({len(answer)} char, min {min_length})")
        logger.warning("Risposta LLM troppo corta", length=len(answer))

    if len(answer) > max_length:
        issues.append(f"risposta troncata ({len(answer)} → {max_length} char)")
        answer = _truncate_at_sentence(answer, max_length)
        modified = True
        logger.info(f"Risposta troncata a {max_length} caratteri")

    answer, artifact_issues = _remove_artifacts(answer)
    if artifact_issues:
        issues.extend(artifact_issues)
        modified = True

    is_valid = len(answer) >= min_length

    if issues:
        logger.debug("Validazione risposta", issues=issues, modified=modified)

    return ValidationResult(
        is_valid=is_valid,
        answer=answer if is_valid else _FALLBACK_ANSWER,
        issues=issues,
        was_modified=modified,
    )

def _truncate_at_sentence(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text

    truncated = text[:max_length]
    last_sentence_end = max(
        truncated.rfind(". "),
        truncated.rfind(".\n"),
        truncated.rfind("! "),
        truncated.rfind("? "),
    )

    if last_sentence_end > max_length // 2:

        return text[:last_sentence_end + 1].strip()

    last_space = truncated.rfind(" ")
    if last_space > 0:
        return text[:last_space].strip() + "..."

    return truncated + "..."

def _remove_artifacts(answer: str) -> tuple[str, list[str]]:
    import re
    issues: list[str] = []
    original = answer

    prefix_pattern = r'^(RISPOSTA|Risposta|ANSWER|Answer|A|Assistant|Assistente)\s*:\s*'
    if re.match(prefix_pattern, answer):
        answer = re.sub(prefix_pattern, '', answer).strip()
        issues.append("rimosso prefisso risposta")

    if answer.startswith("```") and answer.endswith("```"):

        first_line = answer.split("\n")[0]
        lang = first_line.replace("```", "").strip()
        if not lang or lang.lower() in {"", "text", "txt"}:

            answer = re.sub(r'^```\w*\n?', '', answer)
            answer = re.sub(r'\n?```$', '', answer)
            answer = answer.strip()
            issues.append("rimosso markdown fence non necessario")

    closing_patterns = [
        r'\n\nSpero che questa risposta sia stata utile\.?$',
        r'\n\nFammi sapere se hai altre domande\.?$',
        r'\n\nSe hai bisogno di ulteriori chiarimenti.*$',
        r'\n\nLet me know if you.*$',
    ]
    for pattern in closing_patterns:
        new_answer = re.sub(pattern, '', answer, flags=re.IGNORECASE).strip()
        if new_answer != answer:
            answer = new_answer
            issues.append("rimossa frase di chiusura generica")
            break

    return answer, issues