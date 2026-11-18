"""Development-only counterfactual: append unrelated worked examples, leaving grader fixed."""
import sys

from dev import small_model_eval as evaluator

EXAMPLES = '''Examples from a different workspace, not the current request:
Open files: red/ui.ini and blue/ui.ini both contain theme=light.
User: Set the theme to dark in blue/ui.ini.
Assistant: {"action":"fs.edit","arguments":{"path":"blue/ui.ini","old":"theme=light","new":"theme=dark"}}
Tool: edit succeeded.
Assistant: {"action":"done"}
User (independent task): Set the theme to dark in the UI configuration.
Assistant: {"action":"ask","question":"Which UI configuration should change: red/ui.ini or blue/ui.ini?"}
End of examples. Use the actual request and observations below.'''


def main():
    original = evaluator.initial_prompt

    async def with_examples(*args, **kwargs):
        messages = await original(*args, **kwargs)
        messages[0]['content'] += '\n' + EXAMPLES
        return messages

    evaluator.initial_prompt = with_examples
    try:
        return evaluator.main()
    finally:
        evaluator.initial_prompt = original


if __name__ == '__main__':
    sys.exit(main())
